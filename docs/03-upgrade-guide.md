# Upgrade guide: from today's code to the target design

Written 2026-11-11. Part 1 records what the code does today, including the defects the review
found. Part 2 is the ordered plan to reach `02-system-design.md`. Every phase leaves the product
working and releasable.

File references are `path:line` against commit `a38585e`. Lines drift; search for the name.

---

## Part 1. Baseline: the system as built

### 1.1 Shape

- One Python process (`uaf serve`) holds everything: the FastAPI app, one scheduler thread
  (`app/container.py:103`, every 15 s) and N worker threads (`app/workers/runtime.py:154`, default 2).
  Each job runs in a child process (`app/workers/process.py:109`).
- SQLite in WAL mode is the only database ever exercised. The schema is created by
  `Base.metadata.create_all` at start (`app/main.py:75`), not by the five Alembic migrations that
  also exist.
- The queue is the `bus_jobs` table; jobs are enqueued in the engine's transaction
  (`app/bus/db_bus.py:62`).
- 24 tables, 59 API routes, one WebSocket, 27 activities, 453 backend tests, about 280 frontend tests.
- Frontend: shell, sign-in, Operations (dashboard, runs, run detail, schedules, Run now) and a
  `/design` catalogue. Inbox, Studio, Data and Admin are one-line placeholders.

### 1.2 What is sound and stays

| Mechanism | Where | Why it stays |
|---|---|---|
| Outbox: state and next job in one transaction | `app/engine/run_engine.py:502` | The reason a crash never loses a step |
| Attempt number on the envelope; stale results ignored | `run_engine.py:766` | Correct redelivery handling |
| Secret nonce binding per dispatch | `app/domain/workflow.py:217` | Run data can never request a secret |
| Secrets to the child on stdin only, masked at every sink | `app/workers/child.py`, `app/domain/masking.py` | Right boundary |
| Process-tree kill on timeout | `app/workers/process.py:92` | Works on Windows and Linux |
| Hash-chained audit with head counter and ORM guard | `app/audit/` | Good base; needs keying and an outside anchor |
| argon2id, timing equaliser, three-way limiter, hashed session ids, per-session CSRF | `app/security/`, `app/services/auth.py` | Solid |
| Segregation of duties on promotion | `app/services/workflows.py:439` | Core governance rule |
| Layer contract enforced by import-linter | `pyproject.toml:153` | Keeps the code honest |
| Generated OpenAPI types, generated icon paths, token-driven theme | `web/` | Good frontend foundations |

### 1.3 Defects and gaps found in the review

Severity: **H** breaks a guarantee or is a security hole, **M** will hurt at modest scale or
confuses users, **L** cleanup.

**Engine and runtime**

| # | Sev | Finding | Where |
|---|---|---|---|
| E1 | H | Cancelling a run marks the job cancelled but never stops the child process. The activity keeps running (and sending email, writing to Oracle) until it ends or times out | `run_engine.py:1190`, `workers/runtime.py:96` |
| E2 | H | The tick examines the 200 oldest active runs only. With more than 200 active or queued runs, newer ones never get retries, timeout checks or queue release | `run_engine.py:289` |
| E3 | M | A parent run learns its sub-workflow finished only on the next tick: up to 15 s of dead time per sub-workflow. The same applies to retry delays and queued runs | `run_engine.py:681`, `container.py:104` |
| E4 | M | One process-wide lock serialises every engine mutation. A slow commit stalls every run, and the design cannot use a second process | `run_engine.py:92` |
| E5 | M | Only two outcomes and one `current_step`: no conditions, no parallel work, no merge, no wait that does not hold a worker (`sleep` occupies a slot) | `domain/workflow.py:317` |
| E6 | M | `foreach` is sequential and re-reads all prior iteration rows on every dispatch | `run_engine.py:1085` |
| E7 | M | Retries fire on every failure, including ones that can never succeed (bad credentials, validation errors) | `run_engine.py:861` |
| E8 | M | No side-effect idempotency. A redelivered job after a worker crash re-sends the email or re-runs the SQL | activities |
| E9 | L | Dead branch at the end of `_resume_waiting` (looks up a token, then returns either way) | `run_engine.py:713-724` |
| E10 | L | `retry_from_failed_step` accepts a cancelled run but then needs a failed step; the UI offers retry only for failed | `run_engine.py:1261` |

**Declared but not implemented** (each is a promise the product does not keep)

| # | Setting or field | Where declared | Reality |
|---|---|---|---|
| D1 | `data.retention_days` | `config.py:41` | Nothing deletes workspaces or artifacts. Disk grows without bound |
| D2 | `audit.retention_years` | `config.py:53` | Never read |
| D3 | `settings.max_duration_minutes` | `workflow.py:369` | Never read |
| D4 | `Step.disabled` | `workflow.py:333` | Ignored by the engine; a disabled step still runs |
| D5 | `users.must_change_password` | `models.py:46` | Serialised, never set or enforced |
| D6 | `purge_expired_sessions`, `needs_rehash`, `requeue_dead` | `auth.py:335`, `passwords.py:33`, `db_bus.py:324` | Never called |
| D7 | `incidents.resolved` | `models.py:263` | Never set to true |
| D8 | `bus.adapter: rabbitmq`, `rabbitmq_url`, the `rabbitmq` extra | `config.py:78` | Refused at start |
| D9 | `idempotency_keys.expires_at` | `models.py:433` | Rows are never removed |

**Security** (beyond the open items already recorded in the old `SECURITY.md`)

| # | Sev | Finding | Where |
|---|---|---|---|
| S1 | H | SEC-10: any Author can send any secret to any host, loopback included. Decided in ADR 0001, not built | `activities/_common.py:44` |
| S2 | H | Secrets are a plaintext JSON file; `chmod` does nothing on Windows; any activity can read it | `adapters/secrets/local.py:44` |
| S3 | H | Activities run as the server's OS user and can read the database, the secret file and every workspace | `workers/process.py:141` |
| S4 | M | `GET /api/runs` returns run inputs and outputs unmasked and the absolute server path of the workspace | `api/serializers.py` |
| S5 | M | The audit hash is unkeyed and its counter sits in the same database: a database writer can forge a valid chain | `audit/chain.py:18` |
| S6 | M | The alert mailer logs in to SMTP without STARTTLS, so the relay password crosses the network in clear. (The `email` activity refuses this; the notifier does not) | `services/notifications.py:76` |
| S7 | M | No password change or reset, no idle timeout, no session list | `services/auth.py` |
| S8 | M | Behind a reverse proxy every client has the proxy's address, so the per-address limiter and the audit `source_ip` are meaningless | `api/deps.py:28` |
| S9 | M | Webhook tokens live in the URL path, never expire, cannot be rotated and have no rate limit. The payload can override any configured input | `services/schedules.py:438` |
| S10 | M | No per-workflow access: every Viewer reads every run, input, output and file | `api/runs.py` |
| S11 | L | The failed-login audit row stores whatever was typed as the username, so a password typed in the wrong box is kept for 7 years | `services/auth.py:246` |
| S12 | L | API docs and the OpenAPI file are public; `/health` reveals worker count and version; no HSTS; no `Cache-Control: no-store` | `main.py:89` |
| S13 | L | The session signature accepts 30 days regardless of the configured lifetime (the row expiry is what protects) | `security/sessions.py:49` |
| S14 | L | The event socket closes before accepting when the session is gone, so browsers see 1006 and retry for ever | `api/system.py:546` |

**Data**

| # | Sev | Finding |
|---|---|---|
| DB1 | H | Two schema paths. `create_all` at start means a model change reaches a database with no migration, and Alembic's history can disagree with reality |
| DB2 | M | `runs.workflow_id`, `runs.version_id`, `tasks.run_id`, `step_attempts.run_id`, `saved_views.user_id`, `comments.user_id` have no foreign key. `created_by` columns hold usernames in some tables and user ids in others |
| DB3 | M | No check constraints: any string is a valid status |
| DB4 | M | Every save creates a version. The Studio cannot autosave on this model |
| DB5 | M | Oracle as control-plane database has never run; the audit id-contiguity check will fail on it (G15) |
| DB6 | L | `/api/metrics` sums the durations of an arbitrary 1,000 runs and labels it a counter |

**Frontend**

| # | Sev | Finding |
|---|---|---|
| F1 | H | Four of five areas are placeholders. Nobody can build a workflow, act on a task or manage a user in the UI |
| F2 | M | No run-started or step-started event; screens poll while a run is active |
| F3 | M | Run now takes raw JSON because workflows have no input schema |
| F4 | M | `web/dist` is committed, so every UI change is a large binary diff |
| F5 | L | Sidebar highlights Dashboard and Runs together; `apiSend` cannot send headers; `ApiError` drops `details` |

**Process**

| # | Finding |
|---|---|
| P1 | No CI. The gates (ruff, mypy, import-linter, pytest, vitest, vue-tsc, eslint, freshness checks) run only by hand or pre-commit |
| P2 | `README.md` says the console is not started; `BUILD_PROGRESS.md` lists CP-39 as todo while its fixes are merged; the old `SYSTEM_DESIGN.md` says there is no code. Trackers and docs disagree with the code |
| P3 | Real Oracle, Graph, SFTP and portals have never been exercised (G2 to G5) |
| P4 | `runtime/` holds a dev login file and a database backup. It is git-ignored, but check it before sharing the folder |

---

## Part 2. The plan

### How to work

- One phase at a time, each on its own branch, merged only with all gates green.
- Database changes are **expand, migrate, contract**: add the new shape, move data, remove the old
  shape one release later. No migration may need downtime longer than a restart.
- Every behaviour change ships behind a setting when it can surprise an existing workflow, defaults
  to the old behaviour in the release that introduces it, and flips in the next.
- Each phase ends with its exit checks run and recorded.

### Order and size

| Phase | Theme | Depends on | Rough size |
|---|---|---|---|
| 0 | Truth and tooling | none | 1 week |
| 1 | Security closure | 0 | 2 to 3 weeks |
| 2 | Database foundation | 0 | 2 weeks |
| 3 | Engine v2 | 2 | 4 to 5 weeks |
| 4 | Workers and isolation | 2, 3 | 3 weeks |
| 5 | API v1 and live events | 2, 3 | 2 weeks |
| 5b | Connectors and skills | 3, 4, 5 | 5 to 6 weeks |
| 6 | Console build-out | 5 (Studio also needs 3 and 5b) | 9 to 11 weeks |
| 7 | Operate at scale | 4, 5 | 2 weeks |

Phases 1 and 2 can run side by side. Inbox and Admin screens (phase 6) need only today's API and
can start right after phase 1.

---

### Phase 0. Truth and tooling

Goal: one schema path, CI on every change, no dead promises, one name.

1. **CI** (`.github/workflows/ci.yml`): `uv sync --frozen`; ruff check and format check; mypy
   strict; `lint-imports`; pytest with coverage; `pip-audit`; in `web/`: `npm ci`, `api:check`,
   `icons:check`, typecheck, lint, vitest, build, `npm audit --omit=dev`. Fail on any.
2. **Alembic only.** Remove `create_schema=True` from `create_app` (`app/main.py:75`). Add
   `worktree db upgrade | current | check`. `serve` refuses to start when the schema is behind and
   prints the command. Tests keep `create_all` through the test container only. Add a CI job that
   runs `alembic upgrade head` on an empty database and diffs it against the models
   (`alembic check`).
3. **Dead promises (D1 to D9).** For each: implement in the phase named below or delete now.
   Delete now: D8 (`rabbitmq` settings and extra), E9 (dead branch). Implement in phase 3: D3, D4.
   Implement in phase 2: D1, D2, D9. Implement in phase 1: D5, D6 (`purge_expired_sessions`,
   `needs_rehash` on login). D7: add `POST /runs/{id}/incidents/{id}/resolve` or drop the column.
4. **Rename `uaf` to `worktree`.** Package name, CLI entry point (`worktree`, keep `uaf` as an
   alias), env prefix (`WORKTREE_`, read `UAF_` with a deprecation log line), cookie names
   (`worktree_session`, `worktree_csrf`; accept the old session cookie until it expires), log
   event prefixes, metric names (`worktree_*`), `uaf@localhost`, the `__UAF_RESULT__` marker
   (workers and children ship together, so change both at once), CSS variables `--uaf-*` to
   `--wt-*` by codemod (done together with the reskin in release 6.0, since the token values change
   at the same time). Do not rename the database file automatically; change the default and
   document the move.
5. **Stop committing `web/dist`.** Build it in CI, include it in the wheel
   (`tool.hatch.build.targets.wheel.force-include`), remove it from git and add it to `.gitignore`.
   `tests/integration/test_web_bundle.py` builds or skips.
6. **Docs.** Replace `README.md` with a real quick start. Retire `BUILD_PROGRESS.md`,
   `docs/BUILD_CHECKPOINTS.md`, `docs/AGENT_START_PROMPT.md` and the old `SYSTEM_DESIGN.md` in
   favour of this folder. Point the generators at the new location (see `README.md` here).

Exit checks: CI green on a pull request; `alembic check` reports no drift; a fresh install works
with `worktree db upgrade && worktree serve`; `grep -ri uaf` finds only the compatibility shims.

---

### Phase 1. Security closure

Goal: close every H finding that does not need a new engine, and the cheap M and L ones.

| Step | Change | Closes |
|---|---|---|
| 1.1 | Implement ADR 0001: `credential_inputs`, `destination_inputs` on activities; `allowed_hosts`, `environments` on secret metadata (migration); checks at save, dispatch and step test; egress filter in `validate_url` with connect-to-checked-address; `secrets.enforce_policy` with a prod start-up check; secrets listed on promotion requests; names-only secret list for Authors | S1 |
| 1.2 | Encrypted secret store: new `secrets` table, AES-256-GCM, master key from DPAPI or a key file, `worktree secrets migrate` to import and then shred `secrets.json`. Env-var override becomes opt-in and is shown as the source in the Admin list | S2 |
| 1.3 | Mask run-level `inputs` and `outputs` in every run response; replace `workspace` with a boolean `has_workspace` | S4 |
| 1.4 | Audit: HMAC with a key from the secret store's internal namespace; database triggers refusing update and delete; daily signed anchor file; `verify` reads anchors. Old rows keep the old algorithm, marked by a new `algo` column | S5 |
| 1.5 | Notifier uses the same SMTP helper as the `email` activity (STARTTLS required when credentials are set) | S6 |
| 1.6 | Password change (self), Admin reset with `must_change_password`, idle timeout, session list and revoke, rehash on login, purge of expired sessions in the maintenance loop | S7, D5, D6 |
| 1.7 | `security.trusted_proxies`; take the client address from `X-Forwarded-For` only when the peer is trusted | S8 |
| 1.8 | Webhooks: bearer header, hashed storage, rotation, optional expiry, per-token rate limit, payload under `inputs.payload`. The old URL form keeps working for existing triggers until rotated, and is flagged in the UI | S9 |
| 1.9 | Failed login actor becomes `anonymous`; details hold a keyed hash of the typed name | S11 |
| 1.10 | Docs behind sign-in in prod; `/health` returns status only; add HSTS (when `cookie_secure`), `Cache-Control: no-store` on API responses, `Permissions-Policy`; tighten CSP `connect-src` to `'self'` | S12 |
| 1.11 | Signature max age follows `session_ttl_minutes`; accept the socket, then close with 1008 | S13, S14 |

Exit checks: `tests/integration/test_security.py` gains a test per row and has no `xfail`; the A1
and A6 acceptance tests pass with the policy enforced; a manual attempt to post a secret to
`127.0.0.1` as an Author is refused at save and at dispatch; `runtime/secrets.json` no longer exists
after migration.

S3 (runner identity) and S10 (folder access) need phases 4 and 2.

---

### Phase 2. Database foundation

Goal: a schema that can carry the target design, on PostgreSQL as well as SQLite.

1. **PostgreSQL support.** Add `psycopg` and a CI matrix that runs the whole backend suite on
   SQLite and PostgreSQL 16. Fix what differs: the claim query already has the
   `SKIP LOCKED` branch (`db_bus.py:142`, currently marked no-cover); JSON columns become `JSONB` by
   dialect; timestamps `timestamptz`.
2. **Integrity migration.** Add the missing foreign keys (DB2) after a data check script reports
   orphans; add check constraints for every status and kind column (DB3); normalise `created_by`,
   `requested_by`, `decided_by`, `claimed_by` to user ids with a nullable `actor_label` for
   non-user actors (`scheduler`, `webhook`). Expand first: add `*_user_id`, backfill by username,
   switch reads, drop the old columns one release later.
3. **New tables** needed by later phases, created empty now: `workflow_drafts`, `folders`,
   `folder_grants`, `run_tokens`, `timers`, `events`, `workers`, `leases`, `run_step_logs`,
   `secret_uses`, `side_effects`, `api_tokens`, `audit_anchors`, `activity_packages`,
   `run_stats_daily`. Definitions are in `06-database-and-security-plan.md`.
4. **Folders and access (S10).** Backfill `folders` from the existing `workflows.folder` strings;
   everything else goes to the open `General` folder. Add the scoping helper and apply it to every
   list and fetch. Default grants give every role its current reach, so nothing changes until an
   Admin restricts a folder.
5. **Retention (D1, D2, D9).** A maintenance job in the scheduler loop removes expired workspaces,
   idempotency keys, finished jobs and old sessions, and archives audit rows past retention to a
   signed file before deleting them. Dry-run mode and a log line per action.
6. **File store interface.** `FileStore` with `LocalFileStore`; artifacts copied to
   content-addressed storage when a step publishes them; `artifacts.path` becomes
   `artifacts.storage_key`.
7. **`worktree db copy --from sqlite:///... --to postgresql://...`**: table by table, in
   dependency order, in batches, verifying counts and the audit chain at the end.

Exit checks: full suite green on both databases; `db copy` round-trips a database with 50,000 runs
and the audit chain verifies on the target; a restricted folder is invisible to a user without a
grant in every list, fetch, artifact download and event; the retention job frees disk in a test and
never touches an active run.

---

### Phase 3. Engine v2

Goal: the graph model, tokens, event-driven progress, real cancel. The largest phase; do it in
five merges.

**3a. Per-run locking and wake-ups (no model change).**
Replace the global lock with `SELECT ... FOR UPDATE` on the run row inside `advance`. Add the
`timers` table and a one-second timer loop for retries, step deadlines and queued runs. Child
finish and queue release enqueue a wake-up in the finishing transaction. Remove the `LIMIT 200`;
the 60 s reconciliation sweep pages through everything. Closes E2, E3, E4.
Test: 1,000 active runs all progress; a sub-workflow chain of five adds under one second.

**3b. Schema v2 and the converter.**
Add the v2 pydantic models (`nodes`, `edges`, typed `inputs`), the pure `v1_to_v2` function, and a
property test that every valid v1 definition converts to a valid v2 one with the same execution
trace on the old engine tests. The engine reads v2 only; stored v1 rows convert on read. Publish
`reference/schemas/workflow-v2.json`.

**3c. Tokens and engine-side nodes.**
Introduce `run_tokens`. Implement `if`, `switch`, `set`, `stop`, `parallel`, `merge`, `wait`,
`foreach` with `concurrency`, node `disabled` (D4), run `timeout_minutes` (D3) and `on_error`.
Existing runs in flight at upgrade get one token at their `current_step`; `current_step` stays as a
derived, read-only column for one release.
Test: a matrix of small graphs with golden traces; Hypothesis generates random valid graphs and
checks that every run ends, no token is orphaned, and replaying the audit rows reproduces the final
state.

**3d. Expressions.**
The parser and evaluator, the function list, the step budget, and validation of references against
graph dominance. `{{ steps.x.y }}` keeps working as an alias. Fuzz the parser.

**3e. Results and safety.**
Typed errors with `retryable` (E7); `side_effects` ledger and `ctx.idempotency_key` (E8), adopted
by `email`, `oracle_execute`, `oracle_bulk_load`, `unc_archive`, `sftp`; the `cancelling` state and
worker-side kill (E1, completed in phase 4); drafts and publish (DB4) with `If-Match`.

Exit checks: every old engine, recovery and acceptance test passes unchanged against converted
definitions; the crash-recovery test kills the process at each of the commit points and the run
still completes once; cancelling a run with a `sleep 300` step ends the child within 5 s; the A1
workflow rewritten with an `if` and a `parallel` passes.

Risk and rollback: 3a is independently valuable and reversible. 3b to 3e ship behind
`engine.model: v1 | v2`; v1 stays the default until the suite and a week of dev use are clean, then
the default flips, then v1 is removed.

---

### Phase 4. Workers and isolation

1. **Split the roles.** `worktree serve --role`. The container builds only what the role needs. The
   scheduler takes the `leases` row. Default stays all-in-one.
2. **Worker registry and heartbeats.** `workers` table, drain on SIGTERM and on request, orphan
   detection by heartbeat instead of `host:pid` (`db_bus.py:32`).
3. **Pools and priority.** `pool` on activities and jobs; `playwright_*` default to `browser`.
4. **Runner identity (S3).** Run children as the configured low-privilege account
   (`CreateProcessWithLogonW` on Windows through a small helper, `setuid` on Linux). File ACLs set by
   `worktree doctor --fix`: the runner can write its own workspace only.
5. **Limits.** Job Objects and `setrlimit`; per-activity defaults; a job that exceeds memory fails
   with `error.code = resource_limit`.
6. **Scoped loading.** The child imports one activity module. Drop-ins become signed packages;
   loose files in the folder are refused in prod and warned about in dev.
7. **Streaming.** Runner writes log and progress frames on stdout; the worker forwards them to
   `run_step_logs` and `events` in batches (every 500 ms or 50 lines).
8. **Container runner (optional).** `runner: container` for a pool.
9. **Environment allow-list** replaces "inherit everything except `UAF_*`".

Exit checks: a `run_python` step cannot read the database, the config, another run's workspace or
the key file (tests for each); killing a worker host mid-job redelivers within 30 s; draining a
worker loses no job; a step that allocates 4 GB is stopped at its limit and the server stays up.

---

### Phase 5. API v1 and live events

1. Mount routers under `/api/v1`; keep the old paths as thin aliases that log a deprecation.
2. Cursor pagination, the filter and sort grammar, structured validation `details`.
3. `inputs` schema exposed on `GET /workflows/{id}` so Run now can build a form (F3).
4. New resources: `draft`, `folders`, `workers`, `triggers` (the `schedules` routes renamed),
   `signals`, `logs`, `secrets/{name}/policy`, `api-tokens`, `me/sessions`, `me/password`.
5. Events: write to `events` in the causing transaction; SSE endpoint with topics, permission
   filter and `Last-Event-ID`; add `run.created`, `step.started`, `step.progress`, `step.log`,
   `task.created`, `task.updated` (F2). Keep the WebSocket for one release.
6. Regenerate `openapi.json` and `web/src/api/schema.d.ts`; extend `apiSend` for headers and keep
   `error.details` (F5).

Exit checks: OpenAPI freshness check green; a contract test walks every list endpoint with a cursor
to the end; an SSE client that disconnects for 30 s and resumes misses nothing; a user without a
folder grant receives no event for it.

---

### Phase 5b. Connectors and skills

Follow `07-nodes-and-connectors.md` (build order in its section 9.2).

1. Value types in the engine and runner: record, list, table handle, file handle; `run_values`.
2. Connections: tables, API, test action, role resolution per environment, the secret policy
   attached. Existing `{{ secret:name }}` references keep working.
3. The connector framework (`App`, `@operation`, `@options`, `@shape`, `@watch`, `@test`), the
   design-time call pool and cache, and an adapter that presents each old activity name as its new
   operation, so stored workflows run unchanged.
4. Regroup the 27 activities into the built-in apps (mapping in section 9.1 of that document).
   Spreadsheet, Database, Files and Web request first. No behaviour change in this step: the same
   code, reached through the new shape, with the old tests still passing.
5. Sensitive values, named locks and per-connection rate limits.
6. Match and One-time code as the first two skills; then Portal sign-in as the first composite
   skill; then the people skills with named outcome ports.
7. The columnar table tools (filter, join, group and the rest).
8. Remaining apps and skills; "Save as skill".

Exit checks: the A1 acceptance workflow rebuilt from app and skill nodes passes with the same
outputs; a 3-million-row CSV goes through read, filter, match and write without the worker passing
500 MB; a one-time code never appears in the database, logs, API responses or the audit log (the
leak scan covers it); two runs that sign in to the same portal never overlap; every old workflow
version still runs.

---

### Phase 6. Console build-out

Follow `04-ui-reimplementation-guide.md`, a full redesign in the garden theme (seven flower colours
on a light base, the Bloom logo, plant-shaped nodes, device fonts). Order chosen so each release is
useful by itself:

| Release | Screens | Backend needed |
|---|---|---|
| 6.0 | **Reskin**: new tokens and palette, restyled base components, plant drawing functions, area band, workflow flowers, the Bloom logo; the existing Operations screens in the new look | none |
| 6.1 | Home, Inbox (list, detail, all four task forms, board) | today's API after phase 1 |
| 6.2 | Admin: users, roles, sessions; Connections: secrets and policy; audit log with verify | phase 1 |
| 6.3 | Operations upgrade: live runs, run detail with streaming logs, triggers, workers | phases 4, 5 |
| 6.4 | Studio: library, workflow page, versions, diff, promotion | phase 5 |
| 6.5 | Studio editor: canvas, add menu, app and skill setup panels, the widget library, mapping, test run, YAML view | phases 3, 5, 5b |
| 6.6 | Data views, files, Insights, access reviews, activity packages | phases 2, 7 |

Each release: component tests, Playwright end-to-end for its main journeys, an accessibility pass
(keyboard, screen reader labels, contrast in three themes), and a review in compact and comfortable
density.

---

### Phase 7. Operate at scale

1. Prometheus endpoint on its own port; histograms and queue-age gauges; remove the old
   `/api/metrics` sum (DB6).
2. `/healthz` and `/readyz`.
3. Alert rules and channels; the SLA and failure notifications move onto them.
4. Nightly rollups and the Insights API.
5. Monthly partitions for the large tables on PostgreSQL.
6. Runbook: install, upgrade, backup and restore drill, key rotation, drain and patch, restore the
   audit chain from anchors, what each alert means.
7. Load test to the numbers in section 1 of the system design; record the results.
8. Real-system acceptance: Oracle 19c, a Graph tenant, an SFTP host and one real portal (closes G2
   to G5). This needs the organisation's test credentials and is the gate for a production pilot.

---

## Part 3. Compatibility promises

| Thing | Promise |
|---|---|
| Stored workflow versions (schema v1) | Run for ever through the converter. Never rewritten |
| Runs in flight during an upgrade | Finish. Phase 3c migrates each to one token at its current step |
| `UAF_*` variables, `uaf` command, old cookies | Work for one release after the rename, with a warning |
| Unversioned `/api/...` routes and the WebSocket | Work for one release after `/api/v1` and SSE |
| Activities written against the v1 contract | Load unchanged; `output_fields` is read when `output_model` is absent |
| The audit chain | Never rewritten. New rows carry `algo = hmac-sha256`; `verify` handles both |
| SQLite installs | Stay supported for single-node use |

## Part 4. What to do first on Monday

1. Phase 0 items 1 and 2 (CI and Alembic-only). Everything else is safer after them.
2. Phase 1 steps 1.3, 1.5, 1.9 and 1.11: each is under a day and closes a real leak.
3. Phase 1 step 1.1 (ADR 0001), already specified and the top item of the old task queue.
4. Phase 3a: removes the 200-run ceiling and the 15 s waits with no model change.
