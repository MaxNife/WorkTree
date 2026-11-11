# Database and security plan

Written 2026-11-11. Part A is the database: what exists, what is wrong with it, the target schema
and how it is run. Part B is security: what is protected today, what is not, and the controls to
add, in priority order. Both follow `02-system-design.md` and `07-nodes-and-connectors.md`; the
order of work is in `03-upgrade-guide.md`.

---

# Part A. Database

## A1. Where it stands

- 24 tables, defined in `app/adapters/db/models.py`, with five Alembic migrations.
- SQLite in WAL mode is the only engine that has ever run. The Oracle path is written and untested.
- The schema is created by `create_all` when the server starts, not by the migrations.

**Problems found**

| # | Problem | Consequence |
|---|---|---|
| 1 | Two ways to create the schema (`create_all` and Alembic) | A model change can reach a database with no migration; the migration history can disagree with the real schema |
| 2 | Missing foreign keys: `runs.workflow_id`, `runs.version_id`, `runs.parent_run_id`, `tasks.run_id`, `step_attempts.run_id`, `saved_views.user_id`, `comments.user_id`, `processed_files.schedule_id` | Orphan rows are possible and cannot be detected by the database |
| 3 | No check constraints on any status, kind or role column | Any string is accepted |
| 4 | People are recorded inconsistently: `created_by` is a username in some tables and a user id in others; `requested_by` is a username or the words `scheduler` and `webhook` | Joins are unreliable; renaming a user breaks history |
| 5 | Every save creates a version; there is no draft | The Studio cannot autosave |
| 6 | Nothing is ever deleted: workspaces, finished jobs, idempotency keys, expired sessions, events | Unbounded growth. Three retention settings exist and none is read |
| 7 | Secrets live in a JSON file beside the database, in plain text | Covered in Part B |
| 8 | The audit head counter is in the same database as the log | A database writer can forge a valid chain |
| 9 | JSON columns hold whole definitions, inputs and outputs with no size control beyond a 64 kB check in the engine | Large rows; no way to query inside them on SQLite |
| 10 | `bus_jobs.id` and `audit_log.id` rely on gap-free autoincrement | True on SQLite only; breaks the audit check on Oracle |
| 11 | No workflow-level access data (folders are a free-text column) | Every user can read every run |

## A2. Engine choice

| Use | Engine | Why |
|---|---|---|
| Production | **PostgreSQL 16** | Row locks with `SKIP LOCKED` for the queue, `LISTEN/NOTIFY` for wake-ups, `JSONB`, partitioning, real constraints, mature backup. Free and on-premise |
| One node, pilots, development, tests | **SQLite (WAL)** | Zero setup. Kept fully supported |
| Oracle as control-plane database | **Not recommended** | Possible, but every feature above needs separate work and testing. Keep Oracle as a system the workflows read from and write to. Choose it only if policy forbids PostgreSQL (owner decision 1 in the system design) |

The suite runs on SQLite and PostgreSQL in CI. Dialect differences stay inside `app/adapters/db`.

## A3. Conventions for every table

- Primary keys: UUID version 7 as text (time-ordered, so indexes stay compact), except append-only
  logs, which use `bigint` identity.
- Times: `timestamptz`, always UTC. `created_at` on every table; `updated_at` where rows change.
- People: a foreign key `*_user_id` to `users`, nullable, plus `actor_label` for non-human actors
  (`scheduler`, `webhook`, `system`). Never a bare username.
- Status and kind columns: text with a `CHECK` listing the allowed values, matched to the Python
  enums by a test.
- JSON: `JSONB` on PostgreSQL, `JSON` on SQLite, each with a documented shape and a size limit
  enforced in the service layer.
- Soft delete (`archived_at`) for things people create; hard delete only by the retention job.
- Every foreign key has an index. Every query the console runs on a list page has an index that
  matches its filter and sort.
- Optimistic concurrency: a `revision` integer on rows that two people can edit.

## A4. Target schema

Grouped by purpose. **New** tables are marked; others exist and are changed as noted.

### Identity and access

| Table | Key columns | Notes |
|---|---|---|
| `users` | id, username (unique, case-insensitive), display_name, email, auth_source (`local`, `oidc`), password_hash (null for OIDC), totp_secret_enc, is_active, must_change_password, last_login_at, preferences jsonb | Adds email, auth source, TOTP, preferences |
| `roles`, `user_roles` | as today | |
| `sessions` | id (hash), user_id, csrf_token, created_at, last_seen_at, expires_at, idle_expires_at, revoked_at, source_ip, user_agent | Adds idle expiry and last seen |
| `api_tokens` **new** | id, user_id, name, token_hash, permissions[], expires_at, last_used_at, revoked_at | Machine access |
| `folders` **new** | id, parent_id, name, path (unique) | Replaces the free-text folder |
| `folder_grants` **new** | folder_id, role or user_id, level (`view`, `operate`, `author`) | Object-level access |
| `login_attempts` **new** | key, window_start, failures, blocked_until | Rate-limit state shared by all API processes |

### Workflows

| Table | Key columns | Notes |
|---|---|---|
| `workflows` | id, name (unique), folder_id, description, owner_user_id, tags, colour, petals, manual_minutes, archived_at, latest_version | Adds folder FK, the workflow's flower, and manual minutes for the time-saved figure |
| `workflow_drafts` **new** | workflow_id (PK), definition jsonb, revision, updated_by_user_id, updated_at | One editable draft per workflow |
| `workflow_versions` | id, workflow_id, version, definition, schema_version, checksum, note, created_by_user_id, node_versions jsonb | Adds note and schema version. Immutable: a trigger rejects updates |
| `promotions` | as today, with user FKs, plus `evidence jsonb` (diff summary, connections used, test runs) | What the approver saw is kept with the decision |
| `environments` | as today | |

### Runs

| Table | Key columns | Notes |
|---|---|---|
| `runs` | id, workflow_id FK, version_id FK, folder_id, environment, status, trigger, trigger_detail, correlation_id, inputs, outputs, error_code, error, requested_by_user_id, actor_label, concurrency_key, parent_run_id FK, deadline_at, created/started/finished_at | Adds FKs, folder (denormalised for fast access filtering), error code, deadline. `current_step` is removed after the token engine ships |
| `run_tokens` **new** | id, run_id, node_id, state, parent_token_id, item_index | Positions on the graph |
| `run_steps` | as today plus token_id, node_type, app, operation, progress, error_code, pool | One row per node execution |
| `step_attempts` | as today with FK | |
| `run_step_logs` **new** | id bigint, run_id, step_id, ts, level, line | Streamed logs. Partitioned by month |
| `run_values` **new** | run_id, step_id, port, kind (`record`, `list`, `table`, `file`), handle jsonb | Typed outputs: table and file handles |
| `incidents` | as today plus resolved_by_user_id, resolved_at | |
| `artifacts` | id, run_id, step_id, name, storage_key, sha256, bytes, media_type, retain_until | Content-addressed storage key replaces the path |
| `timers` **new** | id, due_at, run_id, kind, payload | Retries, waits, deadlines, SLA |
| `locks` **new** | name (PK), run_id, acquired_at, expires_at; `lock_waiters(name, run_id, queued_at)` | Named locks for single-session systems |
| `side_effects` **new** | idempotency_key (PK), run_id, step_id, result jsonb, created_at | Stops a redelivered write from repeating |
| `signals` **new** | id, run_id, name, payload, received_at, consumed_at | External continuation |

### Work queue and workers

| Table | Key columns | Notes |
|---|---|---|
| `jobs` (was `bus_jobs`) | id, pool, priority, payload, state, attempts, max_attempts, visible_at, claimed_by_worker_id, last_error, result | Adds pool and priority |
| `workers` **new** | id, host, pid, pools[], slots, version, state, started_at, last_seen_at | Heartbeats |
| `leases` **new** | name (PK), holder, expires_at | The single active scheduler |
| `design_cache` **new** | key (hash of app, call, values), result, expires_at | Cached drop-down and shape lookups |

### Triggers

| Table | Key columns | Notes |
|---|---|---|
| `triggers` (was `schedules`) | as today, plus token_hash (replaces the plain token), token_expires_at, calendar_id, rate_limit | The plain webhook token column is dropped after rotation |
| `trigger_cursors` **new** | trigger_id, cursor jsonb, updated_at | State for polling triggers |
| `processed_files` | as today with FK | |
| `calendars`, `holidays` **new** | calendar_id, date, name | Business-day rules |

### People and collaboration

| Table | Notes |
|---|---|
| `tasks`, `task_events` | As today with FKs, plus `form_schema`, `outcome`, `revision` |
| `comments`, `saved_views`, `notifications` | As today with FKs |
| `alert_rules`, `alert_deliveries` **new** | What to alert on, where it went, whether it arrived |

### Connections, secrets and packages

| Table | Key columns | Notes |
|---|---|---|
| `connections` **new** | id, name, role, type, folder_id, settings jsonb, environments[], allowed_hosts[], read_only, rate_limit, lock_name, last_tested_at, last_test_ok | Typed connection |
| `secrets` **new** | name, version, ciphertext, nonce, key_id, created_by_user_id, created_at, retired_at | Encrypted values. Replaces `secrets.json` |
| `secret_policies` (was `secrets_metadata`) | name, description, environments[], allowed_hosts[], allowed_folders[], rotation_days | |
| `secret_uses` **new** | secret_name, connection_id, run_id, step_id, host, used_at | Usage trail |
| `rate_buckets` **new** | connection_id, tokens, refilled_at | Shared rate limiting |
| `packages`, `package_nodes` **new** | name, version, signer, trust, enabled; node key, operations jsonb | Installed connectors and skills |

### Audit and events

| Table | Key columns | Notes |
|---|---|---|
| `audit_log` | as today plus `algo`, `actor_user_id`, `folder_id` | Append-only. Database triggers reject update and delete |
| `audit_head` | as today | |
| `audit_anchors` **new** | day, last_id, head_hash, signature, written_to | Record of each signed daily anchor |
| `events` **new** | id bigint, topic, type, folder_id, payload, created_at | Feeds the live stream. Kept 24 hours |
| `idempotency_keys` | as today; `expires_at` set and enforced | |
| `run_stats_daily` **new** | day, workflow_id, environment, runs, done, failed, p50_ms, p95_ms, task_wait_ms | Feeds Insights |

## A5. Indexes that matter

| Query | Index |
|---|---|
| Runs list, newest first, by folder | `runs (folder_id, created_at DESC)` |
| Active runs | partial `runs (created_at) WHERE status IN ('queued','running','waiting','cancelling')` |
| Concurrency guard | partial `runs (workflow_id, concurrency_key) WHERE status IN (active)` |
| Claim a job | partial `jobs (pool, priority DESC, id) WHERE state = 'pending'`, on `visible_at` |
| Due timers | `timers (due_at)` |
| My open tasks | partial `tasks (assignee_role, due_at) WHERE status IN ('open','claimed')`, and `(claimed_by_user_id)` |
| Steps of a run | `run_steps (run_id, started_at)` |
| Audit by object and by time | `audit_log (resource_type, resource_id, id)`, `(ts)` |
| Event tail | `events (id)`, `(topic, id)` |

Budget: every list page under 500 ms at p95 with 2 million runs. A CI job loads a generated data
set of that size weekly and fails if a watched query exceeds its budget.

## A6. Migrations

1. Alembic is the only way the schema changes. The server refuses to start if the database is
   behind, and says which command to run.
2. **Expand, migrate, contract.** A release adds new columns and tables and writes to both shapes;
   the next release reads only the new shape; the one after drops the old. No migration needs more
   downtime than a restart.
3. Every migration has a downgrade, tested in CI by upgrading an empty database to head, down one
   and up again, on both engines.
4. Data migrations are separate, restartable scripts (`worktree db migrate-data <name>`) that work
   in batches and report progress. They never run inside a schema migration.
5. Before any migration that adds a foreign key or constraint, a check script lists the rows that
   would violate it. The migration refuses to run while any exist.
6. `worktree db copy` moves a SQLite install to PostgreSQL table by table and verifies row counts
   and the audit chain at the end.

## A7. Retention

| Data | Kept | Then |
|---|---|---|
| Run workspaces | 30 days after the run ends (setting, per workflow override) | Deleted |
| Artifacts | Per workflow: 90 days by default, up to 7 years | Deleted, with an audit row |
| Run and step rows | 2 years online | Moved to yearly archive partitions, still queryable |
| Step logs | 90 days | Dropped by partition |
| Finished jobs | 7 days | Deleted |
| Events | 24 hours | Dropped |
| Sessions, idempotency keys, design cache, login attempts | Until expiry | Deleted hourly |
| Sensitive run values (one-time codes, session tokens) | Until the run ends | Destroyed |
| Audit log | 7 years (setting) | Exported to signed archive files, verified, then removed from the table |

Each rule is a named job in the scheduler with a dry-run mode, a log line per action and a metric.
A setting that exists is enforced; a setting that is not enforced is deleted.

## A8. Backup and recovery

| Item | Method | Target |
|---|---|---|
| PostgreSQL | Continuous WAL archiving plus a nightly base backup | Lose at most 5 minutes; restore within 1 hour |
| SQLite installs | Hourly online backup (`VACUUM INTO`) to another disk | Lose at most 1 hour |
| File store (workspaces, artifacts) | Nightly incremental copy | Lose at most 24 hours of files |
| Master key for secrets | Kept outside the database backup, in the OS key store and one sealed offline copy | A database backup alone cannot reveal a secret |
| Audit anchors | Written to a separate share as they are made | Survive the loss of the database |

A restore drill runs every quarter: restore to a clean machine, start the server, verify the audit
chain against the anchors, run one workflow. The drill's result is recorded.

## A9. Growth

At 5,000 runs a day with 10 steps each, a year adds about 1.8 million runs, 18 million step rows
and 60 to 100 million audit rows. Monthly partitions on `run_steps`, `run_step_logs`, `audit_log`
and `events` keep indexes small and make retention a partition drop. Run inputs and outputs above
8 kB move out of the row into `run_values`.

---

# Part B. Security

## B1. What is being protected, and from whom

**Assets**, most valuable first: credentials for portals, the ledger database, mailboxes and
shares; the financial data that passes through runs; the integrity of approvals and the audit
record; the ability to run code on the server.

**Who might attack**

| Actor | Can already | Wants |
|---|---|---|
| Outsider on the network | Reach the sign-in page and webhooks | A session, or to start runs |
| Viewer or Operator | Read runs they should not see | Data from other teams |
| **Author** (the main internal threat) | Build workflows and name secrets | To take a credential out, or to change data without review |
| Malicious or mistaken package | Run inside a worker | Everything the worker can reach |
| Someone with database write access | Change rows | To hide what they did |
| Admin | Everything | Out of scope: Admins are trusted, but their actions must be recorded where they cannot erase them |

## B2. What already holds

Keep these; they are well built and tested:

- argon2id password hashing; a timing equaliser for unknown users; refusal of well-known passwords.
- A three-way sign-in limiter (per pair, per address, per account).
- Opaque session tokens, signed in the cookie and stored only as a hash; `HttpOnly`, `SameSite=Lax`;
  refusal to start in prod without `Secure`.
- A per-session CSRF token checked on every state-changing route.
- Role checks on every route and again in the services; the last Admin cannot be removed.
- Segregation of duties on promotion.
- Secrets passed to the activity on stdin only, bound to a per-dispatch nonce, masked at every
  output.
- The control-plane database refused to SQL activities; archive writes confined to allowed roots;
  workspace path confinement; zip-slip protection.
- A scrubbed child environment; process-tree kill on timeout.
- Hash-chained audit with an append-only guard.
- Fixed error bodies with a correlation id; a strict content security policy.

## B3. What does not hold, and the plan

Priority: **P0** before any production data, **P1** before wide use, **P2** hardening.

### Identity and sessions

| P | Gap | Control |
|---|---|---|
| P0 | No password change or reset; `must_change_password` unused | Self-service change; Admin reset that forces a change at next sign-in; minimum length 12 for local accounts |
| P0 | Behind a proxy, every client shares one address | `security.trusted_proxies`; read `X-Forwarded-For` only from them |
| P1 | No single sign-on | OIDC with Entra ID through the existing `Authenticator` protocol; group to role mapping; local accounts kept for break-glass and alarmed when used |
| P1 | No idle timeout, no session list | 30-minute idle expiry beside the 8-hour limit; a session list with revoke; all sessions revoked on password change and role change |
| P1 | Limiter state is per process | `login_attempts` table |
| P2 | No second factor for local accounts | TOTP, required for Admin |
| P2 | A mistyped password in the username box is stored in the audit log | Failed attempts recorded as `anonymous` with a keyed hash of the typed name |
| P2 | The signed cookie is accepted for 30 days regardless of settings | Signature age follows the configured lifetime |

### Authorisation

| P | Gap | Control |
|---|---|---|
| P0 | Run inputs, outputs and the server path of the workspace are returned unmasked to any Viewer | Mask both; remove the path |
| P1 | No object-level access: everyone sees every run | Folders and grants; one scoping helper applied to every list, fetch, download, comment and live event; tests that walk every route as a user without the grant |
| P1 | Write and change operations are as easy as reads | Operation kinds: `write` and `change` need the Author role in the folder, respect a read-only flag on the connection, and are shown to the approver |
| P2 | API documentation is public | Sign-in required in prod |

### Secrets and connections

| P | Gap | Control |
|---|---|---|
| P0 | **Any Author can send any secret to any host** (SEC-10) | ADR 0001 in full, attached to connections: placement (credential fields only), destination (the connection's own hosts), environment (dev by default), egress filter. Refuse by default |
| P0 | **Secrets are a plaintext file** | `secrets` table, AES-256-GCM per value, master key from DPAPI (Windows) or a root-only key file or kernel keyring (Linux), or Vault. A migration command imports and then destroys the file |
| P1 | Environment variables silently override stored secrets | Opt-in only, and shown as the source in the console |
| P1 | No rotation support | Versioned secrets with a grace period; rotation reminders from `rotation_days`; a rotation is one action on the connection |
| P1 | One-time codes and session tokens appear in step outputs | Sensitive values: never stored, masked, destroyed at run end, accepted only by credential inputs |
| P2 | Masking misses encoded forms | Also register the base64 and URL-encoded forms of each resolved secret |
| P2 | Browser session files are plain JSON on disk | Encrypt with the master key; scope by connection, not by portal name |

### Running activities

| P | Gap | Control |
|---|---|---|
| P0 | A cancelled run's step keeps running | Workers kill the process tree on cancel |
| P1 | **Activities run as the server's own OS user** and can read the database, the key and other runs' files | A separate low-privilege runner account with access to its own workspace only; file permissions set and checked by `worktree doctor` |
| P1 | No memory, CPU or process limits | Job Objects on Windows, `setrlimit` and cgroups on Linux, with defaults per pool |
| P1 | Every job imports every file in the drop-in folder | Signed packages only in prod; the runner imports only the module it needs |
| P1 | The child inherits most of the server's environment | An allow-list |
| P2 | Code nodes rely on the Admin role alone | Optional container runner per pool; required before anyone but an Admin may use Code |
| P2 | Package setup screens could carry script | Declarative widgets only; a package cannot ship code that runs in the browser |

### Network

| P | Gap | Control |
|---|---|---|
| P0 | No protection against requests to loopback, link-local and metadata addresses | One `check_destination` used by every connector: resolve, check every address against denied and allowed networks, connect to the checked address, re-check on redirect |
| P1 | Webhook tokens sit in the URL, never expire, have no rate limit, and the payload can override configured inputs | Bearer header or HMAC signature with a timestamp; stored hashed; rotation and expiry; per-token rate limit; payload confined to `inputs.payload` |
| P1 | The alert mailer sends its SMTP password without STARTTLS | Use the same mail helper as the Email connector, which refuses that |
| P1 | File triggers may watch any folder | Confined to configured roots, never inside the data folder |
| P2 | No HSTS, no `Cache-Control: no-store`; the health check reveals version and worker count | Add the headers; split health into a bare liveness check and an authenticated readiness check; metrics on a separate loopback port |

### Data integrity

| P | Gap | Control |
|---|---|---|
| P1 | The audit chain is unkeyed and its counter is in the same database | HMAC with a key outside the database; database triggers refusing update and delete; a signed anchor written daily to a separate share; verification checks against the anchors |
| P1 | A redelivered job repeats its side effect | The idempotency ledger for `write` and `change` operations |
| P1 | Destructive SQL is as easy as a query | Statement parsing before dispatch; `UPDATE` or `DELETE` without `WHERE`, and any DDL, need the connection to allow it and are flagged at promotion |
| P2 | Two schema paths | Alembic only (Part A) |
| P2 | Promotion evidence is not kept | Store what the approver was shown with the decision |

### Supply chain and process

| P | Gap | Control |
|---|---|---|
| P0 | No continuous integration | Every change runs lint, types, layer check, tests on both databases, `pip-audit` and `npm audit` |
| P1 | Dependencies are ranges | Locked and hashed installs (`uv sync --frozen`, `npm ci`); a weekly update job |
| P1 | No software bill of materials | Generated per release (CycloneDX) |
| P2 | paramiko's licence is unresolved (G10) | Legal ruling, or switch to `asyncssh` |

## B4. Logging, detection and response

- **Security events** go to the audit log and to the operating system's log (Windows Event Log or
  syslog) so the organisation's monitoring can collect them: sign-in success and failure, lockouts,
  role and grant changes, secret and connection changes, promotions, package installs, policy
  refusals (a secret or host that was blocked), audit verification results.
- **Alerts** by default: more than 20 failed sign-ins in 5 minutes; any break-glass local sign-in
  when SSO is on; a policy refusal in prod; audit verification failure; a run in prod by a version
  with no approved promotion (should be impossible; alert if seen); a worker with no heartbeat.
- **Runbook entries**: revoke a user everywhere; rotate a leaked credential (rotate, find uses from
  `secret_uses`, review runs); rotate the master key; respond to a failed audit verification
  (compare with the anchors, find the first differing row, preserve the database); disable a
  package.

## B5. How each control is proven

Every row in B3 gets a test in `tests/integration/test_security.py`, named for what it stops, and
an entry in the threat model. Standing checks:

| Check | What it does |
|---|---|
| Route walk | For every route in the OpenAPI file and every role, and for a user without a folder grant: assert the expected status |
| CSRF walk | Every state-changing route rejects a missing or wrong token (exists today) |
| Secret leak scan | After the acceptance runs, search logs, the database, API responses and workspaces for every planted secret value and its encoded forms |
| Egress tests | Loopback, link-local, metadata, a redirect to each, and a DNS name that changes between check and connect |
| Runner confinement | A code step tries to read the database, the key, the config, another workspace and the package folder; each must fail |
| Audit tamper | Edit a row, delete the last row, recompute hashes without the key, reset the counter; each must be detected |
| SQL lint | No query in the codebase built by string formatting (exists today) |
| Dependency audit | Fails the build on a known vulnerability above low severity |

Before the first production use: an independent penetration test of the console and API, and a
review of the runner confinement on the real servers.

## B6. Production readiness checklist

The server refuses to start in `prod` unless all of these are true (the first exists today):

1. Cookies are `Secure` and the site is served over HTTPS.
2. The secret policy is enforced.
3. A master key is present and the plaintext secret file is absent.
4. The schema is current.
5. The runner account is configured and is not the server's own account.
6. Trusted proxies are set, or the server is reached directly.
7. API documentation is protected.
8. An audit anchor location is configured and writable.
9. Loose activity files are absent from the package folder.

`worktree doctor` checks the same list, plus file permissions on the data folders, and explains
each failure.
