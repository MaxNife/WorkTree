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
