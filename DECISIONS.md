# DECISIONS

Architecture and process decisions for the UAF Python/FastAPI MVP. Newest entries at the end of
each section. Every deviation from the reference design and every resolved `[UNKNOWN]` is recorded here.

## 1. Reference model (2026-10-22)

**Decision:** Elsa is the primary workflow reference (engine and workflow semantics); n8n is a
secondary reference for workflow behaviour and Studio UX. Neither is a dependency. The explicit
text of `docs/BUILD_PROMPT_python_mvp.md` wins over both.

**Why:** user direction of 2026-10-22, recorded in `docs/SYSTEM_DESIGN.md` §0.4. Re-implementing
Elsa's concepts in Python keeps the semantics the reference .NET design assumes (named outcomes,
bookmarks, retries, versioned activities, rebuilt schedules) without a .NET runtime.

**Consequences:** activities complete with named outcomes and never raise; failures route through
`on_failed`; a suspended run stores a resume token; every retry attempt is recorded; sub-workflows
pin a version; schedules are rebuilt from the DB at startup. Nothing is copied from n8n. No Elsa
source was adapted, so no MIT notice is carried.

## 2. Runtime and dependencies

| # | Decision | Why |
|---|---|---|
| 2.1 | Python **3.12** via uv (`requires-python >=3.12,<3.14`) | 3.14 is the system interpreter, but pandas/pyarrow/calamine/playwright wheel availability is not guaranteed for it. 3.12 is installed and supported by every dependency. |
| 2.2 | Hatchling build backend; `uv` manages the venv and `uv.lock` | plain `uv sync` on Windows and Linux; the lockfile is committed. |
| 2.3 | `paramiko` for SFTP | it is LGPL, flagged by the research notes for a legal ruling. Recorded in `KNOWN_GAPS.md`. It is isolated behind the `sftp` activity; `asyncssh` is the alternative if legal rejects it. |
| 2.4 | `python-oracledb` thin mode, imported lazily | keeps SQLite the default; no Oracle client libraries required for tests. |
| 2.5 | `pyarrow` for Parquet, `pandas` for chunked CSV work | matches the research notes; both ship wheels for 3.12. |
| 2.6 | `apscheduler` 3.x (`BackgroundScheduler`) rebuilt from the DB | Elsa rebuilds schedules from stored triggers; APScheduler 3 is the stable API. |
| 2.7 | Vault (`hvac`), RabbitMQ (`aio-pika`) and OpenTelemetry are optional extras | the default install must work offline against fixtures; the adapters are import-guarded. |

## 3. Layering and module map

**Decision:** `app.api` → `app.services` → `app.engine` → `app.workers`/`app.audit`/`app.security`
→ `app.bus` → `app.adapters` → `app.domain`, enforced by import-linter. `activities/` is a separate
top-level package that imports only `app.domain.activity`.

The ORM lives in `app.adapters.db.models`; pure workflow/envelope types live in `app.domain`.
FastAPI route modules validate input with pydantic and call a service; no business rules live in a
route handler. `app.container` wires the concrete adapters (DB, bus, secret store, clock, audit) so
tests can replace any of them.

**Why:** the checkpoint requires API → services → domain → adapters. Inserting `engine`, `workers`,
`bus`, `security` and `audit` between services and adapters keeps the dependency direction while
letting the engine use the bus and workers.

## 4. Configuration and secrets

| # | Decision | Why |
|---|---|---|
| 4.1 | Config keys use a nested `config.yaml`; environment overrides use `UAF_` + `__` (e.g. `UAF_DATABASE__URL`) | pydantic-settings native behaviour, no bespoke parser. Full key list in `config.yaml`. |
| 4.2 | No admin password is ever configured by default. `serve` refuses to start until an admin user exists and rejects `admin`/`password`/`changeme` when bootstrapping. | satisfies R14 without committing a credential. `create-user` is the supported path. |
| 4.3 | Default secret store = process env, then a git-ignored JSON file at `runtime/secrets.json` (mode 0600), plus an optional HashiCorp Vault adapter | "env vars + optional config file" from the spec; the file is the only writable store for the auto-generated session signing key. Values never enter the repo or logs. |
| 4.4 | Session signing key is stored as secret `session_signing_key`, generated on first start | keeps the key out of source/config and stable across restarts. |
| 4.5 | Session = signed, HttpOnly, SameSite=Lax cookie; CSRF = double-submit token in `uaf_csrf` cookie + `X-CSRF-Token` header on every mutating request | no third-party auth dependency; SSO can replace `app.security.sessions` behind its interface. |

## 5. Data contract and DB choices (closes SD §6.5 / §13 q18-q20)

Table and column names: `docs/DATA_MODEL.md` (generated from the models; `scripts/gen_data_model.py --check` keeps it current).

**Workflow YAML (version `1`)** — top level: `schema_version`, `name`, `description`, `owner`,
`tags`, `settings` (`duplicate_guard: allow|reject|queue`, `duplicate_guard_key`,
`catch_up`, `sla_minutes`, `persistence: none|summary|full`), `steps`. Step: `id`, `activity`,
`inputs`, `on_done`, `on_failed`, `timeout_seconds`, `retries` (`count`, `delay_seconds`,
`backoff`), `resume: restart|skip`, `foreach`, `foreach_item`, `workflow` (sub-workflow pin:
`{name, version}`), `persist`. Start step = the first entry in `steps` unless a step has
`start: true`. Ending a run = empty/absent `on_done` after a `done` outcome.

**Envelope (version `1`)** — in: `schema_version`, `run_id`, `step_id`, `activity`, `inputs`,
`secret_refs`, `workspace`, `correlation_id`, `timeout_seconds`; out: `schema_version`, `run_id`,
`step_id`, `outcome` (`done|failed`), `outputs`, `message`, `artifacts` (list of
`{name, path, sha256, bytes}`), `correlation_id`. `docs/ENVELOPE.md` carries the JSON Schema.

**Tables** (SQLAlchemy/Alembic): `users`, `roles`, `user_roles`, `sessions`, `workflows`,
`workflow_versions`, `environments`, `promotions`, `schedules`, `runs`, `run_steps`,
`step_attempts`, `incidents`, `resume_tokens`, `tasks`, `task_events`, `artifacts`,
`secrets_metadata`, `audit_log`, `notifications`, `saved_views`, `idempotency_keys`,
`bus_jobs`, `processed_files`, `file_triggers`.

**Resolved [UNKNOWN]s:** Parquet library = pyarrow; session mechanism = signed cookie + CSRF
header; envelope carries `schema_version` and `correlation_id` at the top level of both directions;
config keys as listed in `config.yaml`; `ctx` API = `ActivityContext(run_id, step_id, workspace,
clock, log, secrets)`.

## 6. Engine semantics

| # | Decision | Why |
|---|---|---|
| 6.1 | One run advances one step at a time; the engine persists state after every attempt and only dispatches the next step once the previous result is stored | simplest correct durable model; matches the run lifecycle in the spec. |
| 6.2 | `human_task` is intercepted by the engine (not executed in the worker): it creates the task, writes a resume token and suspends the run | the worker must not own run state; this is the bookmark model. The activity class still exists and passes the contract tests when run directly. |
| 6.3 | Sub-workflow steps are engine-level: a child run is created and the parent waits; the child's terminal outputs are copied to the parent step | prevents re-entrant worker calls; keeps version pinning in the run snapshot. |
| 6.4 | Branching is by outcome routing only (`on_done`/`on_failed`); no separate condition node | Elsa's named-outcome flowchart, and the simplest expression that satisfies the spec. |
| 6.5 | Retries use `count`, `delay_seconds`, `backoff` (multiplier applied per attempt) and are persisted per attempt | every attempt must be visible in run detail. |
| 6.6 | Crash recovery (revised in the CP-01 review): on startup, jobs claimed by worker processes on this host that are no longer alive go back on the bus, so a `resume: restart` step re-runs as a redelivery of the **same** job; a step whose job is gone is re-dispatched; a `resume: skip` step is marked done and its job cancelled. Each job carries the step's `attempt`, and results from another attempt are ignored | re-dispatching on recovery left the original job on the bus, so the step ran twice; tying results to the attempt makes redelivery safe. |
| 6.7 | Duplicate guard key is a dotted path into the trigger payload/inputs (or the literal `workflow`); modes `reject`, `queue`, `allow` | covers "same workflow or a configured key within it". |
| 6.8 | The default bus is a DB-backed queue (`bus_jobs`) with a per-job lease, attempts and dead-letter; the worker pool runs in the serve process, each activity in a child OS process. A worker extends a job's lease to the activity timeout + 60 s on claim; worker ids are `host:pid:name` | meets durability and process isolation without a broker; a fixed 300 s visibility timeout let a second worker pick up a still-running long activity. |
| 6.9 | Every dispatched step stores its `bus_job_id`. Each tick reconciles a dispatched step with its job: a result the worker acked but whose callback never applied is applied; a dead-lettered or cancelled job fails the step; a step past its timeout + 120 s has its job cancelled before it is retried | the worker acks before the engine callback runs, so a crash between them must not strand the run. |
| 6.10 | Engine mutations (`start_run`, `tick`, `on_result`, `recover`, cancel, retry) are serialised by an in-process lock | the scheduler thread and the worker threads otherwise raced on the same run rows. |

## 7. Frontend

| # | Decision | Why |
|---|---|---|
| 7.1 | Vite + Vue 3 + TS strict, Pinia for client state, TanStack Query for server state, Vue Router, Vue Flow, Fluent UI Web Components wrapped in thin local components | exactly the specified stack. |
| 7.2 | The generated API client (`web/src/api/generated.ts`) is produced from `docs/openapi.json`; `npm run check:client` regenerates and diffs | CI fails when the client is stale, as required. |
| 7.3 | The built bundle is committed under `web/dist/` and served by FastAPI at `/` | running the platform must not need Node. |
| 7.4 | Fluent web components are used where they fit; the data grid, canvas, property panel and command palette are our own components on the same tokens | the spec explicitly permits building missing components ourselves rather than adding a second UI kit. |

## 8. Delivery process

| # | Decision | Why |
|---|---|---|
| 8.1 | Local git only, no remote, no history rewrite; checkpoint commits plus `wip()` commits | `docs/AGENT_START_PROMPT.md` §6. |
| 8.2 | Fixtures are real local servers started by pytest; large generated data is written under `tests/generated/` (git-ignored) | deterministic and no production systems. |
| 8.3 | The `.pptx` named in the tracker is absent from the working tree. The baseline commit contains every file that exists. | cannot commit a file that is not present; logged in `KNOWN_GAPS.md`. |

## 9. CP-01 code review (2026-10-22)

| # | Decision | Why |
|---|---|---|
| 9.1 | The audit writer updates a single `audit_head` row before reading the chain tail | that write takes the SQLite write lock (Oracle: row lock) for the rest of the caller's transaction, so concurrent transactions can no longer chain onto the same tail and fork the hash chain. Portable, and needs no global `BEGIN IMMEDIATE` (which would deadlock FastAPI's split dependency/route threads). |
| 9.2 | Activities flagged `requires_admin_author` (`run_python`, `legacy_robot_wrapper`, `ai_extract`) can only be saved in a workflow by an Admin | the flag existed but was not enforced, letting an Author run arbitrary code on the server. |
| 9.3 | Prod runs only a version that has its own approved prod promotion; prod promotion needs that exact version approved in test | previously any older version, or any version below a test-approved one, passed. |
| 9.4 | Cron: the next fire is strictly after the previous one; without `catch_up` a fire more than `misfire_grace_seconds` (default 60) late is skipped and audited as `schedule.missed`; `catch_up` comes from the schedule config, else the workflow's `settings.catch_up` | `catch_up` re-fired the same slot forever, and missed runs were never skipped. |
| 9.5 | Secrets shorter than 4 characters are not masked | masking every "a" corrupts all outputs and JSON keys; such a secret protects nothing. |
| 9.6 | The Vault token is read from the environment variable named by `secrets.vault_token_env` | config holds no secret values. |
| 9.7 | ruff runs in pre-commit from the uv-locked environment, not a pinned hook repo | the pinned v0.8.6 hook and the locked ruff disagreed on rules. |
| 9.8 | `app.main` has no module-level `app`; use `uvicorn app.main:get_application --factory` or `uaf serve` | importing the module built a container and opened the default database. |
| 9.9 | The local secret store reads the environment only through `UAF_SECRET_<NAME>` (name upper-cased, `-./` → `_`); platform secrets (`session_signing_key`, `uaf_internal_*`) cannot be saved in a workflow and are never resolved by a worker; the Vault adapter treats only `InvalidPath` as missing | resolving any env var name let a workflow read the server's own credentials (e.g. `VAULT_TOKEN`), and reading the signing key would allow session forgery; a Vault outage must fail loudly. |
| 9.10 | "Run this step" (`POST /api/activities/{name}/test`) runs through the same child-process launcher as a worker (timeout, process-tree kill), resolves secrets with the worker's rules, requires CSRF, and code-running activities are Admin-only | it previously ran activities inside the API process with no timeout, resolved any secret (including the session signing key) in the control plane, had no CSRF guard and let an Author run `run_python`. |
| 9.12 | No RabbitMQ adapter in the MVP; `bus.adapter: rabbitmq` is refused at startup | the engine writes the run state and the next job in one transaction (an outbox), which a broker cannot join, so a broker adapter needs an outbox relay; the config value used to be accepted and silently ignored. |
| 9.11 | The auth boundary is the `Authenticator` protocol (`resolve_session`, `check_csrf`) in `app/services/auth.py`; `AuthService` is the local implementation. Empty and well-known default passwords are refused in the service layer, not only in the CLI | SSO can replace the backend without touching routes; the admin API could previously create a user with password `password`. |

## 10. Activity-library review (2026-10-23)

| # | Decision | Why |
|---|---|---|
| 10.1 | `matching` pairs 1:1: each right row is used at most once (exact normalised key first, else best fuzzy score among keys with unused rows); every input row ends up either in a pair or in the unmatched file | right rows with duplicate keys were collapsed into one dictionary entry, so they vanished from both outputs, and one right row could be paired with many left rows. 1:N stays a CP-26 item. |
| 10.2 | `unc_archive` move is copy, verify, then delete; the copy is always checked against `expected_sha256` or else the source hash, and a bad copy is removed | the move deleted the source before checking the checksum, so a mismatch lost the only good copy. |
| 10.3 | SMTP credentials are only sent when the relay offers STARTTLS; `graph_read_mail` filters sender and timestamp in `$filter` with an OData-escaped literal instead of filtering a page after `$top` | without STARTTLS the fallback password crossed the network in clear text; client-side sender filtering could miss the newest matching mail when other senders wrote more often. |
| 10.4 | Delimited/fixed-width reads stream in `chunk_size` batches and write Parquet row groups (or CSV/JSON) incrementally; ZIP extraction enforces a declared and actual uncompressed-size cap plus an entry-count cap; LibreOffice recalculation is opt-in and fails clearly when `soffice` is absent | the 1M-row CSV gate must stay under 500 MB, and a ZIP's declared sizes are attacker-controlled. Measured 55.8 MB traced peak for 1M rows. |

## 11. Platform review and CP-24 to CP-26 (2026-10-23)

| # | Decision | Why |
|---|---|---|
| 11.1 | The engine tick advances each run in its own transaction; a failing run gets an `engine_error` incident in a fresh transaction | one shared session meant a run that failed half-way still had its partial changes committed at the end of the tick. Savepoints were rejected: pysqlite's SAVEPOINT handling can commit the outer transaction. |
| 11.2 | Lock order is always engine lock, then database write lock. `TaskService.complete` takes the engine lock before its first write; `complete_human_task` runs under the engine lock | a task decision could race the scheduler tick on the same run, and taking the lock after writing could deadlock against SQLite until the busy timeout failed one side. |
| 11.3 | `duplicate_guard: queue` really queues: the duplicate is created `pending` and is not advanced until the run ahead of it finishes; queue order is (`created_at`, `id`); recovery leaves queued runs pending | the duplicate was marked queued but advanced at once, so it ran in parallel; with equal timestamps two queued runs waited for each other forever. |
| 11.4 | `human_task` inputs are validated by the activity's own input model in the engine; `assignee_role` is a `Role` | an unknown type or role created a task nobody could complete; a bad number crashed the tick. |
| 11.5 | Activity child processes never inherit `UAF_SECRET_*` or the Vault token variable (`VAULT_TOKEN` plus `secrets.vault_token_env`); child settings travel as `UAF_CHILD_*` variables (`UAF_CHILD_PLAYWRIGHT_STATE`) | the child got the server's whole environment, so any activity code could read the session signing key or the Vault token (contradicting 9.9). |
| 11.6 | The public webhook answers with the run's `id`, `status` and `trigger` only, and refuses bodies over 1 MiB or that are not a JSON object | the token is the only credential, and the full run record exposed inputs, the server workspace path and the correlation id; the body becomes persisted run inputs. |
| 11.7 | The last active Admin cannot be demoted or deactivated (409); unknown users are 404; an unknown username costs the same argon2 verification as a wrong password | removing the last Admin left nobody able to manage users, secrets or roles; the timing difference revealed which usernames exist. |
| 11.8 | Playwright portal lock covers only session load/check/login/save, not the steps; a lock is abandoned only when its owner pid is gone; login failure markers and their selector are inputs | robots on one portal were serialised end to end; a 5-minute staleness rule could break a live login waiting up to 900 s for an OTP; fixed words like "invalid" anywhere on a landing page looked like a failed login. |
| 11.9 | `legacy_robot_wrapper`: env from inputs (no `UAF_*` names), `success_codes` plus `exit_code_messages`, `output_files` glob patterns confined to the workspace (missing ones fail unless `require_output_files: false`); `run_python` and the wrapper kill the whole process tree on timeout and keep the partial output | CP-25 build items; a robot's helper processes (e.g. Excel) must not outlive the step. `run_python` is documented as process isolation, not a sandbox (Admin-only). |
| 11.10 | `matching` (now `activities/matching.py`) is a pure function: exact normalised keys by default (`threshold` 1.0; lower allows fuzzy keys, never in 1:N), optional amount tolerance (Decimal) and date tolerance; 1:1 chooses highest score, then smallest amount gap, then earliest row; 1:N groups all unused same-key rows in the date window whose amounts sum to the left amount; outputs `<name>`, `<name>-unmatched-a`, `<name>-unmatched-b` | CP-26; replaces 10.1's single unmatched file. Exact keys by default because a reconciliation must not pair "INV-3" with "INV-30" unless asked. |
| 11.11 | `ai_extract` sends a JSON Schema (`response_format: json_schema`, `strict`) and validates the answer with jsonschema before it reaches the workflow; `jsonschema` becomes a runtime dependency | CP-26: results from a model are untrusted input. Still off by default and pending AI-framework approval. |
| 11.12 | PDF work uses pypdf (BSD-3-Clause), in process and confined to the run workspace by `safe_path`: info, text, combine, extract_pages, split, protect (AES-256; restrictions only behind a permissions password), watermark (hand-written Helvetica content stream), fill_form, optimize. Redact, OCR and `script` are not offered. Supersedes the earlier PdfCraft-binary design | Binding decision: no Storytold/CraftApps binary at runtime; pypdf is small and permissive; redaction that only hides text is worse than none (KNOWN_GAPS G16) |
| 11.13 | Word-processing work edits plain `.docx` XML with zipfile + lxml (`activities/_docx.py`): text, info, convert to txt/md/html, and mail merge ported from WordCraft (CraftApps, MIT OR Apache-2.0): MERGEFIELD as fldSimple or fldChar runs, one section per record, template untouched, recipients from CSV/TSV/XLSX or inline rows, drawing ids renumbered. No binary, no PDF rendering. Supersedes the earlier WordCraft-CLI design | Binding decision: no binaries at runtime; XML is parsed without entity resolution or network access and parts are size-capped |
| 11.14 | Spreadsheet calculation uses our own Python engine (`activities/_formula`: parser, evaluator and ~140 functions ported from GridCraft, MIT OR Apache-2.0) for the `spreadsheet` activity and `excel` recalculation. Results are written back by editing the sheet XML (charts and images survive, `calcChain` dropped, `fullCalcOnLoad` set) with Excel-valid error codes (`#CIRC!` is written as `#VALUE!`); LibreOffice is never used. Protections kept: data starting with `=` stays text, formulas only from the `formulas` input, leading-zero numerals stay text, no nan/inf. Supersedes the GridCraft-CLI design | Binding decision 3: recalculation must not use LibreOffice; evaluation uses an explicit work stack so long dependency chains do not hit the recursion limit |
| 11.15 | Frontend dependencies are pinned exactly (`web/.npmrc` save-exact, lockfile committed). Beyond the packages named in CP-27 only tooling was added: vitest, @vue/test-utils and jsdom (component tests), typescript-eslint, eslint-plugin-vue, vue-eslint-parser and globals (ESLint, including no explicit `any`), @vitejs/plugin-vue, openapi-typescript (the API type generator), @types/node, and Fluent's two required peers. TypeScript stays on 5.9.x because typescript-eslint (<6.1) and openapi-typescript (^5) do not support later majors. No HTTP client, UI kit or icon library is added | Advisor-approved dependency list for CP-27; keeps the supply chain small |
| 11.16 | Theme tokens live in one TypeScript source (`web/src/theme/tokens.ts`) that uses Fluent's token names and is written as CSS custom properties, so wrapped Fluent components and our CSS share it; three themes (light, dark, high contrast) follow the OS with a manual override, accent Fluent green #107C10 as one token, compact density by default. Text/background pairs are unit-tested against WCAG AA 4.5:1 (this caught a failing dark-theme button hover). Screens never use Fluent elements directly; they use our `U*` wrappers. UI choices are in `docs/design-language.md` | Product owner's UI decisions of 2026-10-23; one colour source avoids drift |
| 11.17 | After the owner flagged "AI-designed tells" on the first design page, the visual language was simplified: Fluent System Icons (MIT, `@fluentui/svg-icons` as a dev dependency, paths generated into `src/icons/paths.ts`) replace our hand-drawn set; status is a dot plus text; node cards and panels are flat; empty states are plain text; the logo is a two-tone WorkTree wordmark (green Work, brown Tree) with the sprout beside it. The product name is WorkTree everywhere user-visible; the `uaf` command, `UAF_*` variables and package names are unchanged | Owner decisions of 2026-10-23 (icons: use a real set; logo: wordmark with sprout); avoids generic AI-generated styling |

## 12. Wave 1 review (2026-11-05)

| # | Decision | Why |
|---|---|---|
| 12.1 | An `api_token` portal login saves no browser state | it never reuses a session, and its empty state made a later form login on that portal look already signed in, so the password was never tried |
| 12.2 | The worker leaves a secret reference the step did not declare as plain text; `substitute_secrets` stays strict by default | declared secrets that are missing already fail in the worker, so what remains is data from an earlier step |
| 12.3 | An inline `run_python` script is deleted as soon as its process ends | once substituted it holds secrets in plain text |
| 12.4 | A queued run always waits for an active run that is not queued, then queued runs go in (created_at, id) order | comparing ids alone let a queued run start beside the active run when both had the same timestamp |
| 12.6 | Each dispatch binds the saved step's secret references to a random nonce before data is merged in, and the worker resolves only those. The single-step test endpoint does the same, with secret names taken from the request, not from pinned data | data from a portal page or an email cannot reach a secret, even one the step uses itself |
| 12.5 | The A6 grep lists GET routes from the OpenAPI schema | FastAPI no longer flattens included routers into `app.routes`, so the old list missed most of the API |
| 12.7 | A SQL activity's `db_url` (`secret_only_inputs`) may only be a single `{{ secret:name }}` reference unless an Admin saves or tests the step; at run time `open_database` also refuses a SQLite URL that resolves to the control-plane database, compared by resolved path, hard link and `ATTACH`, and no longer creates folders | a free `db_url` let an Author read `users.password_hash` and rewrite roles in the control-plane database (SEC-1). Both layers stay: the first keeps Authors from typing connection strings, the second holds if an Admin's secret or an old saved workflow points there. A non-Admin who omits `db_url` still gets the fixed default. Versions already stored are not re-validated; they are only guarded at run time, and an Author who edits one must replace a typed `db_url` with a secret reference |
| 12.8 | `unc_archive` writes only inside `activities.archive_roots` (default empty, so it is off until an Admin lists folders), never inside `activities.extra_folder` even when a root contains it, and the final file is checked as well as the folder | the activity could copy any workspace file into the drop-in folder every job imports (SEC-3). The check uses resolved paths so `..`, links and a crafted `filename` cannot step out. The roots and the protected database path reach the child as `UAF_CHILD_ARCHIVE_ROOTS` and `UAF_CHILD_PROTECTED_DB`, because the child does not load config.yaml |
| 12.9 | A `prod` server whose `security.cookie_secure` is false refuses to start (in `create_app` and in `uaf serve`) instead of forcing the flag on | forcing it silently would hide a misconfiguration, and an operator behind a TLS proxy must say so (SEC-6) |
| 12.10 | Login limits are three: 10 per (username, address) as before, 50 per address across usernames and 30 per account across addresses, in the same 60 s window with a 60 s block. A successful login clears only its own (username, address) bucket | the default numbers are above the pair limit so a person mistyping hits the pair limit first. The account limit can lock a real user out for a minute while someone guesses, the price of stopping a distributed guess. Behind a reverse proxy every client shares one address, so the 50 limit then applies to everyone together (SEC-5) |
| 12.11 | An activity child inherits no `UAF_*` variable from the server; non-`UAF_` variables (`PATH`, proxy and certificate settings, cloud credentials) are still inherited | the child needs everything it reads through `UAF_CHILD_*`, so the control-plane configuration (database and broker URLs) has no reason to reach activity code. Dropping the other variables would break the tools activities start, and `test_activity_children_never_inherit_platform_credentials` expects them kept (SEC-4) |
| 12.12 | The audit writer shortens each field to its column width before hashing, and the admin API refuses secret names over 100 characters and platform secret names | the hash used to cover the full text while the row stored a part, so one long name made `verify` fail for good (SEC-2, SEC-7). Rows already written with that mismatch cannot be repaired: the log is append-only |
| 12.13 | The `/api/events` socket checks the session before every event and every 15 s, and refuses a present `Origin` that is not the request host, both with close code 1008 | a logged-out or deactivated user kept receiving events, and a page on another port of the same host could open the socket (SEC-8) |
| 12.14 | The 500 response is built inside the request middleware, carries `correlation_id` in its body and gets the same security headers as every response | the server-error handler runs outside the middleware, so a 500 had neither (SEC-9) |
| 12.15 | Secret scoping and host filtering (SEC-10) are not changed here; see G17 | the owner has to decide who may use which secret and which hosts `http_request` may reach |
