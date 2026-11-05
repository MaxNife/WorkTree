# WorkTree security model (CP-39)

This is a threat model for the control plane (`app/`), the activity library (`activities/`) and
the worker processes. It says what is protected, what is not, and which gaps are open defects.
Code is cited as `path:line` against the commit this file was written on; line numbers drift,
so search for the name if one is off. `tests/integration/test_security.py` pins every protection
below that says "tested"; a strict `xfail` there is an open defect (SEC-n, listed at the end).

Decisions already accepted are not re-argued here: `DECISIONS.md` 4.x, 9.x, 11.x, 12.x and
`KNOWN_GAPS.md` G1 to G16. `KNOWN_GAPS.md` has no G17 although `DECISIONS.md` 12.2 refers to
one, so what G17 accepts is unknown to this review.

## Scope and trust assumptions

- One server, one OS user. The API process, the worker threads and every activity child run as
  the same operating-system user and share the same disk (`app/workers/process.py:116`).
- The database (`runtime/uaf.db`), the secret file (`runtime/secrets.json`), the workspaces and
  the drop-in activity folder all live on that disk.
- TLS is terminated outside the app. The app sets `Secure` on cookies only when configured to.
- An **Admin** is trusted with the server. An Admin can create more Admins, rotate any secret,
  save code-running activities and read the audit log. Nothing here defends against an Admin.
- Activities are **not sandboxed**. See "Activity execution".

Actors, from least to most privileged: anonymous, Viewer, Operator, Author, Approver, Admin.

## Authentication and sessions

| Property | State | Where |
|---|---|---|
| Passwords | argon2id, 64 MiB, t=3, p=4, random salt. Tested. | `app/security/passwords.py:8` |
| Unknown user costs one hash verification, so timing does not reveal usernames | protected | `app/security/passwords.py:27`, `app/services/auth.py:225` |
| Well-known and empty passwords refused when creating a user (min length 8) | protected. Tested. | `app/services/auth.py:108`, `app/config.py:22,197` |
| Session cookie | signed (itsdangerous), holds a random 256-bit token; the database stores only its SHA-256 | `app/security/sessions.py:43,64` |
| Cookie flags | `HttpOnly`, `SameSite=Lax`, `Path=/`; `Secure` only if `security.cookie_secure` (default false). Tested. | `app/api/auth.py:51-62` |
| Session lifetime | absolute, `session_ttl_minutes` (480). No idle timeout, no rotation, no concurrent-session cap | `app/security/sessions.py:90` |
| Logout and deactivation | logout revokes the row; deactivating a user deletes all their sessions. Tested. | `app/services/auth.py:198` |
| Login throttling | 10 failures per 60 s per (username, address), then a 60 s block. Tested. | `app/security/rate_limit.py:29-58` |
| Password change or reset | none exist. A user cannot rotate their own password | n/a |

Not protected:

- **Password spraying.** The limiter key contains the username, so one address can try one
  password on every account without ever being blocked, and the bucket table is never purged
  (30 distinct usernames left 30 buckets). SEC-5.
- **`Secure` in production.** `app.environment: prod` does not force `Secure`; an operator who
  forgets `cookie_secure: true` sends the session cookie over plain HTTP. SEC-6.
- **Behind a reverse proxy** every client has the proxy's address (`app/api/deps.py:28`), so the
  per-address part of the limiter key stops meaning anything.
- **Login CSRF** is not prevented (no token on the login form); `SameSite=Lax` blocks the
  cross-site POST in current browsers.
- **Failed-login audit rows record the typed username as the actor** (`app/services/auth.py:246`),
  so an attacker can write `auth.login.failed` rows in the name of a real user, and a user who
  types their password into the username box leaves it in the audit log. Read from the code, not
  exercised.

## CSRF

Every state-changing route depends on `csrf_guard` (`app/api/deps.py:58`). The token is a random
value stored in the session row, returned by login and `/api/auth/me`, and compared in constant
time (`app/security/sessions.py:94`). The `uaf_csrf` cookie is only a convenience copy for the SPA;
the server compares the header with the database value, not with the cookie.

Tested: every `POST`/`PUT`/`PATCH`/`DELETE` in `app.openapi()` except login and the webhook
answers 403 to a missing or wrong token, and a token from another session is refused.

Not protected: the WebSocket (`/api/events`, `app/api/system.py:495`) has no `Origin` check.
`SameSite=Lax` keeps a cross-site page from sending the cookie, but a page on another port of the
same host (same site) can open the socket. Events carry ids and masked messages only. Unverified.

## Role-based access and separation of duties

The matrix is in `app/security/rbac.py:28-56`. Routes declare a permission with `require(...)`
(`app/api/deps.py:50`); service methods re-check roles where it matters.

| Role | Can | Cannot |
|---|---|---|
| Anonymous | `GET /health`, `POST /api/auth/login`, `POST /api/hooks/{token}`, `/api/docs`, `/api/redoc`, `/api/openapi.json`, static files | anything else (401, tested) |
| Viewer | read workflows, runs (including inputs, outputs and the workspace path), dashboard, activities, tasks; download any artifact | change anything |
| Operator | Viewer + start and retry runs, act on tasks, saved views, comments | save workflows, admin |
| Author | Viewer + save workflows (not code-running activities), edit, request promotion, start runs, use "Run this step" for non-code activities | approve, admin, audit log |
| Approver | Viewer + decide promotions (not their own, not for versions they wrote), request promotion, act on tasks, read and verify the audit log | save workflows, admin |
| Admin | everything, including code-running activities and users, secrets, schedules | being the last Admin removed (409, tested) |

Controls, all tested:

- Only Author and Admin save workflows (`app/services/workflows.py:66`). Only Admin can save or
  "Run this step" an activity with `requires_admin_author` (`run_python`, `legacy_robot_wrapper`,
  `ai_extract`, `playwright_robot`, `playwright_script`): `app/services/workflows.py:80-91`,
  `app/api/system.py:207`.
- Segregation of duties: a promotion request cannot be decided by its requester, nor by the
  author of the version (`app/services/workflows.py:419-428`). Prod runs need an approved prod
  promotion of that exact version (`app/services/workflows.py:468-475`; tested through a webhook and a manual run).
- User and secret administration and schedules are Admin only (`app/api/admin.py`,
  `app/api/schedules.py`); the audit log is Approver and Admin only.

Limits to know:

- Segregation compares usernames. An Admin can create a second account and approve with it; the
  audit log shows both. This is inside the Admin trust boundary.
- There is no per-workflow or per-folder access control. Any Viewer can read every run's inputs,
  outputs and files (`app/api/runs.py:417`, `app/api/serializers.py:169`).
- Role changes take effect at once: roles are read from the database on every request.

## Secrets handling and masking

- Secrets are referenced as `{{ secret:name }}`, resolved by the worker per call and passed to the
  child on stdin, never in the environment, job row or workspace (`docs/ENVELOPE.md`,
  `app/workers/runtime.py:23-38`, `app/workers/child.py`). Each dispatch binds the saved step's
  references to a random nonce, so run data cannot request a secret
  (`app/domain/workflow.py:192-230`, `DECISIONS.md` 12.6). Tested for the "Run this step" path.
- Platform secrets (`session_signing_key`, `uaf_internal_*`) cannot be used by workflows or by
  step tests (`app/adapters/secrets/base.py:39-43`, `app/services/workflows.py:69`). Tested.
- The admin API never returns a value (`value: null`), the list shows names only, and the audit
  row for a rotation holds only the name (`app/api/admin.py:138-175`). Tested.
- Masking replaces secret values that this process has resolved, in API errors, step results and
  logs (`app/security/masking.py`, `app/main.py:93`). Values under four characters are not masked
  (DECISIONS 9.5). Transformed values (base64, URL-encoded, split across fields) are not masked.
  A secret that no step has resolved yet is not registered with the masker.
- The child environment drops `UAF_SECRET_*` and the Vault token (`app/workers/process.py:33-49`,
  DECISIONS 11.5).

Not protected:

- **Secrets are not scoped.** Any Author can name any secret in any step or step test and send it
  to a URL they choose with `http_request` (verified: an Author's `bearer_token:
  "{{ secret:payroll_key }}"` reached a listener on 127.0.0.1 in clear). That includes loopback
  and internal hosts, because `validate_url` only checks the scheme and refuses embedded
  credentials (`activities/_common.py:44`). SEC-10.
- **The secret file is plaintext JSON.** It is written first and `chmod`ed after
  (`app/adapters/secrets/local.py:44-49`); on Windows `chmod` does nothing, so the file is as
  readable as the NTFS ACL of `runtime/`. Any activity child, and any Author with SEC-1, can read
  it if the path is known.
- **The admin API accepts platform secret names**, so an Admin can overwrite
  `session_signing_key`; sessions break on the next restart. SEC-7.
- Env-var secrets (`UAF_SECRET_*`) override the file silently, so a rotation through the API can
  report success and change nothing.

## The audit chain

Each row stores `prev_hash` and a SHA-256 over its fields (`app/audit/chain.py:18`); the writer
serialises appends through the `audit_head` row (`app/audit/writer.py:71-110`). The ORM refuses to
update or delete rows (`app/audit/guard.py:15,24`). `GET /api/admin/audit/verify` detects an edited
row and rows cut from the end (`app/audit/writer.py:113`). Tested.

Not protected:

- The hash is **unkeyed and the head counter lives in the same database**. Anyone who can write
  the database can rewrite rows, recompute every later hash and set `audit_head.appends`, and
  `verify` will report the chain as intact. The chain is tamper-evident against accidents and
  unsophisticated edits, not against a database writer. Today that includes any Author, via SEC-1.
  Fix: anchor the head hash outside the database (WORM storage, a signed daily export) or key the
  hash with a secret the database does not hold.
- **A long field breaks verification.** The writer hashes the full `resource_id` but stores the
  first 100 characters (`app/audit/writer.py:87-96`). An Admin rotating a secret with a 101 to 200
  character name makes `verify` report "tampered audit row" from then on, hiding any real tamper.
  SEC-2.

## Webhook and file triggers

- A webhook's only credential is its token: 24 random bytes, URL-safe
  (`app/services/schedules.py:70`). Only an Admin sees tokens in listings
  (`app/api/schedules.py:43`). The endpoint reads at most 1 MiB, accepts only a JSON object and
  answers with the run id, status and trigger only (`app/api/schedules.py:118-160`, DECISIONS 11.6).
  Unknown and disabled tokens answer 404. A prod webhook cannot start a run without an approved
  promotion. Tested.
- The payload is merged over the configured inputs, so a caller can override any configured
  input. Run inputs are data: a secret reference inside them stays text (nonce binding).
- Not protected: tokens are never rotated or expired; they sit in the URL path, so proxies and
  access logs keep them; there is no per-token rate limit, so a leaked token can queue runs
  without bound (`duplicate_guard` is the only brake). Unverified under load.
- File triggers watch any folder the server can read (`app/services/schedules.py:324`). Creating
  a trigger is Admin only; the watched path and file name become run inputs. Nothing checks that
  the folder is outside `runtime/`.

## Activity execution

`run_python` and `legacy_robot_wrapper` (and `playwright_script`) are **process isolation, not
sandboxes**. Each job runs in its own child process with a timeout
and a process-tree kill, a scrubbed environment and the run workspace as its working directory
(`app/workers/process.py:78-116`). Nothing limits what that process can do as the server's OS
user: it can read and write any file the server can, open any network connection, read
`runtime/secrets.json` and `runtime/uaf.db`, and import any installed package. Memory and CPU are
unlimited. That is why they are Admin-only to author; the protection is the role gate, not the
process. A workflow saved by an Admin that runs `run_python` runs with the server's full power
for every user who can start it.

Other points:

- The child inherits the parent's environment except `UAF_SECRET_*`, `UAF_CHILD_*` and the Vault
  token, so `UAF_DATABASE__URL` (an Oracle password), `UAF_BUS__RABBITMQ_URL` and any other
  `UAF_*` or cloud variable reach activity code. SEC-4.
- Every job re-imports every `*.py` file in the drop-in activity folder
  (`app/domain/activity_registry.py:35-51`, `app/workers/child.py:73`). Anything written there runs
  with server privileges. SEC-3 shows an Author can write there.
- A step's `timeout_seconds` bounds time only. "Run this step" accepts up to 900 s per call
  (`app/api/schemas.py`).

## SQL access

- The control plane uses SQLAlchemy with bound parameters. A test scans `app/` and `activities/`
  and fails on SQL built with f-strings, `+`, `%`, `.format` or `.join`. The only reviewed
  exceptions are the identifier-interpolating statements in `activities/database.py:187,226,247,
  261,270`, whose identifiers pass `quote_identifier` (`activities/database.py:66`). Tested,
  including injection attempts through `load`, `merge` and `delete_all`.
- The SQL activities (`gl_query`, `oracle_query`, `oracle_execute`, `oracle_bulk_load`) run the
  statement the author writes. Values are bound and positional placeholders are refused
  (`activities/database.py:73`), but the statement itself is arbitrary SQL, including DDL and
  PL/SQL.
- **`db_url` is unconfined.** It is a free input (`activities/sql.py:17,56,82`) and none of these
  activities is Admin-only. `open_database` accepts any `sqlite:` or `oracle` URL
  (`activities/database.py:284`) and creates missing folders for a SQLite file
  (`activities/database.py:132`). An Author can point a step at `runtime/uaf.db` (the path is shown
  to every Viewer in `workspace`, `app/api/serializers.py:169`) and read `users.password_hash`,
  rewrite `user_roles` to become Admin, or edit `audit_log` and `audit_head` (the ORM guard does
  not apply to raw SQL). Verified read-only by `SELECT count(*) FROM users` through "Run this
  step". The write and escalation steps were not run. SEC-1. An Oracle URL also lets an Author put
  a database password into a saved workflow instead of a secret reference.

## File paths activities can reach

- File inputs go through `safe_path` (`activities/_common.py:16`) which calls `ActivityContext.path`
  (`app/domain/activity.py:85`): the path is resolved (symlinks included) and must stay inside the
  run workspace. Tested for `..`, absolute and backslash paths. Zip extraction checks each entry
  (`activities/files.py:421-424`); artifact downloads re-check the stored path
  (`app/api/runs.py:428-431`, tested); SFTP key and host-key files go through `safe_path`.
- Exceptions, none confined to the workspace:
  - `unc_archive.destination_dir` is a bare `Path(...)` created and written to
    (`activities/network.py:415`). The activity exists to write to network shares, but it is not
    Admin-only and has no allow-list of destinations. An Author can copy any workspace file,
    including one they produced with `http_request`, into the drop-in activity folder. Verified
    up to the copy landing there; the import on the next job is read from the code, not run. SEC-3.
  - SQLite `db_url` (above) reads and creates files anywhere.
  - File triggers read any folder (above).
  - `legacy_robot_wrapper` `working_dir` and the `executable` run anything (Admin only).
- Pinned-run test workspaces copy only regular files inside the source workspace
  (`app/api/system.py:304-312`); a step test never writes to the pinned run.

## The Playwright robot

`playwright_robot` and `playwright_script` are Admin-only to author
(`activities/browser.py:116,453`). The robot logs in with credentials from secret references and
reuses a saved browser session per portal (`activities/browser.py:571-600`): the state file name is
a hash of the portal name or host, or a validated simple name, so state is **shared by every
workflow that names the same portal**. State files hold live session cookies in plain JSON under
`runtime/playwright-state`; `chmod 0700` is best effort and does nothing on Windows. The robot
follows whatever URLs the admin wrote, including internal ones; `playwright_script` is arbitrary
Python with the page, context and `ctx` injected (no sandbox). SFTP uses `RejectPolicy`, so unknown
host keys are refused (`activities/network.py:174`). `validate_url` blocks credentials in URLs.

## Cross-cutting

- Security headers: CSP (`default-src 'self'`, no `unsafe-eval`, `frame-ancestors 'none'`),
  `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy` (`app/main.py:67-84`). No HSTS and no
  `Cache-Control: no-store` on authenticated responses or artifact downloads. They are not set on
  a 500 either (SEC-9).
- Unhandled errors return a fixed JSON body with no exception text, class or trace
  (`app/main.py:120`). Tested. The body says to "see the server log" but carries no correlation id
  to find the entry (SEC-9).
- `/api/docs`, `/api/redoc` and `/api/openapi.json` are public (`app/main.py:59-61`), so the whole
  API surface is visible to anonymous callers. `/health` also reveals the worker count and version.
- The validation error handler returns pydantic's error list including the offending input
  (`app/main.py:100-107`); it only echoes what the caller sent.

## Open findings

| Id | Severity | Summary | Test |
|---|---|---|---|
| SEC-1 | High | SQL activities accept any `db_url`; an Author can read and write the control-plane database | `test_an_author_cannot_point_a_sql_activity_at_the_control_plane_database` |
| SEC-3 | High | `unc_archive` writes anywhere, including the drop-in activity folder every job imports | `test_an_author_cannot_archive_a_file_into_an_arbitrary_server_folder` |
| SEC-10 | Medium | Any Author can send any secret to any host, loopback included (secrets unscoped, no SSRF filter) | none: no protection exists to pin |
| SEC-5 | Medium | Login limiter is per (username, address): spraying is unlimited, buckets never purged | `test_one_address_cannot_spray_a_password_across_many_usernames` |
| SEC-2 | Medium | Long `resource_id` makes audit verification fail permanently | `test_a_long_resource_name_does_not_break_the_audit_chain` |
| SEC-6 | Medium | `prod` environment does not force the `Secure` cookie flag | `test_prod_environment_sets_secure_cookies_without_extra_configuration` |
| SEC-4 | Low | Activity children inherit non-secret `UAF_*` variables, including DB and broker URLs | `test_activity_children_do_not_inherit_the_control_plane_configuration` |
| SEC-7 | Low | Admin API accepts the platform secret names | `test_the_admin_api_refuses_to_overwrite_platform_secrets` |
| SEC-8 | Low | Event socket keeps delivering after logout; no `Origin` check | `test_a_logged_out_session_stops_receiving_websocket_events` |
| SEC-9 | Low | 500 responses have no correlation id and no security headers | `test_an_unhandled_error_response_keeps_the_correlation_id_and_security_headers` |
