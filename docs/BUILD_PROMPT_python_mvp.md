# Build prompt: WorkTree, Python/FastAPI MVP

You are building a working MVP of the **WorkTree**: a standalone, on-premise automation platform with its own interface and identity, in **Python with FastAPI**. Read these first, in order: `docs/SYSTEM_DESIGN.md` (repository map, do-not-break rules R1-R36, open questions), `docs/HANDOFF.md` (the Elsa research summary: Elsa is the major workflow reference for this build), `docs/UI_reference_list.md` (UI references per area) and the research notes in `docs/research/`. Then read the section "Workflow reference model: Elsa first, n8n second" at the end of this prompt. Build the whole thing as one coherent piece of software, not in stages. Start from `docs/AGENT_START_PROMPT.md`: it defines the work loop, local git commits, and the progress tracker `BUILD_PROGRESS.md`. The checkpoints in `docs/BUILD_CHECKPOINTS.md` are resume markers, not stages, so never stop at them. Do not stop to ask me questions; where something is unclear, pick the simplest reasonable option, write it in `DECISIONS.md`, and keep going.

## What this is, and who it's for
Hope, a solutions developer. This is a serious platform build, not a toy: write it the way a senior engineer would write the first version of a system that will grow to hundreds of automations and several contributors. Readable, typed, tested and documented beats clever.

This is a **personal MVP** he will use on his own projects and refine heavily, so it must be a foundation that can be hardened without a rewrite. The reference .NET design uses .NET 10 + Elsa Workflows 3 + Temporal + RabbitMQ + Vault + Vue 3. **Deliberate differences here:** the control plane and robots are Python/FastAPI instead of .NET, and the frontend keeps **Vue 3** but is designed as a **blend of Microsoft, n8n and Notion** (see section 4). Everything else about the vision (layers, run lifecycle, governance, roles, success targets) should carry over. Where the reference stack names a .NET-only product (Elsa, MassTransit, Serilog), build the Python equivalent ourselves behind the same idea.

## The vision
**Problem to solve:** hand-written standalone Python automations (Selenium/Firefox portal login with OTP via Graph -> Oracle GL/source query -> bespoke logic -> Excel report -> email -> UNC archive), triggered by Windows Task Scheduler. Gaps: no reuse, no owner interface (outcomes only by email), no live status, no human-in-the-loop, no self-service re-runs, no audit/segregation of duties, credentials in scripts, no lifecycle control (no duplicate-run guard, no promotion). Demand is heading toward hundreds of automations.

**Three audiences:** Engineers compose automations in a low-code studio from a library of reusable governed activities; process owners trigger, monitor and action through a self-service console and task inbox; governance covers every run (immutable audit, vaulted credentials, segregation of duties).

**Success targets to design and test against:**
- A new automation from existing activities in <= 3 working days (so activities must be reusable and well documented).
- Live progress latency <= 5 s. Console dashboard load <= 2 s at p95.
- Audit retention >= 7 years, immutable.
- Availability goal 99.5% in working hours (design for restart-safety; no HA work needed for the MVP).

**Six layers (map each to code):**
1. Experience: Workflow Studio, Operations Console, Task Inbox.
2. Control plane: orchestration, scheduler, version registry, RBAC, audit.
3. Robot fabric: Playwright robots, wrapped legacy robots, workers.
4. Activity library: GL query, SFTP, email, Excel, matching, human task, AI extract (plus file tools).
5. State and data: control-plane DB, message bus, secret vault (and a data lake, out of scope here).
6. Observability and security: structured logs, OpenTelemetry hooks, SLA-breach alerting.

**Run lifecycle:** Trigger (cron, webhook, file arrival, manual, or dependency on another workflow) -> control plane creates the run in the DB and dispatches jobs -> message bus holds jobs with retries -> worker pulls secrets from the vault and runs the activity -> console shows live progress, result and artifacts. Every step audited. Runs that were mid-flight when the service crashed must **resume** (this is what Temporal is for in the reference design). One job/result envelope for every worker language.

## Hard constraints
- Python 3.11+, FastAPI backend. Write the engine ourselves; do not build on another orchestration product (n8n, Airflow, Prefect, Temporal, Elsa, etc.). Ordinary open-source libraries are fine. Elsa and n8n are design references, not dependencies: model the engine on Elsa's concepts and use n8n for workflow behaviour and builder UX, as set out in "Workflow reference model" at the end of this prompt.
- Prefer permissive licences (MIT/BSD/Apache); avoid GPL/LGPL where a good alternative exists. Keep `LICENSES.md`.
- No secret may exist outside the secret store: not in code, repo, logs, run records, artifacts or the UI.
- Customer data stays on-premise: no calls to external SaaS from the platform itself (AI activities must call a configurable local/internal endpoint, off by default).
- Plain `pip install`/`uv sync` on Windows or Linux. Docker optional.
- Keep these behind small swappable interfaces so the reference stack can replace them later: **database** (SQLite default; Oracle via SQLAlchemy + python-oracledb thin mode as an option), **message bus** (default: a durable in-process/DB-backed queue; optional RabbitMQ adapter via aio-pika), **secret store** (default: env vars + optional config file; optional HashiCorp Vault adapter via hvac), **durable resume** (own DB-backed run state; an optional Temporal adapter is not required).

## What to build

### 1. Control plane (FastAPI)
- REST API (OpenAPI docs on) for workflows, versions, environments, runs, tasks, schedules, users/roles, audit, secrets metadata (never values), artifacts.
- **Workflow definition:** YAML/JSON graph of steps. Each step: id, activity type, inputs (plain values or references like `{{ steps.download.files[0] }}` or `{{ secret:portal_x_password }}`), `on_done` / `on_failed` routing by **outcome**, `timeout_seconds`, `retries` (count, delay, backoff). Support branching, `foreach` over small lists, and calling a sub-workflow. Validate before save (unknown activity, bad reference, unreachable step, cycle) with clear messages.
- **Version registry and lifecycle:** every save creates an immutable version. Environments `dev`, `test`, `prod`. A version is promoted dev -> test -> prod only with an Approver's decision, and **an Author cannot promote their own workflow** (segregation of duties, enforced in the API and tested). Prod runs only use promoted versions.
- **Triggers:** cron (APScheduler), webhook (per-workflow token), file arrival (watch a folder/UNC path), manual (Run now), and dependency (start when another workflow finishes with a given outcome). Missed-run behaviour per workflow (skip by default, `catch_up: true` optional).
- **Duplicate-run guard:** the same workflow (or a configured key within it) can't run twice at once; second trigger is rejected or queued per setting, and the reason is recorded.
- **Run engine:** a run id, per-run workspace folder, correlation id on every log line. Each step is a job on the bus, executed by a **worker process** (separate OS process, timeout, process-tree kill on timeout) via the single job/result envelope: `{run_id, step_id, activity, inputs, secret_refs, workspace}` in, `{outcome: done|failed, outputs, message, artifacts}` out. Run state is persisted after every step so an interrupted run resumes from the last completed step on restart (steps must be idempotent or declare `resume: restart|skip`). A hung or crashed worker never takes the control plane down.
- **Live progress:** push step events to the console over WebSocket (or SSE) within 5 s; the dashboard endpoint must load in <= 2 s p95 with a few thousand runs in the DB (add the indexes and a test that measures it).
- **RBAC:** roles Viewer (dashboards, run history), Operator (trigger runs, action tasks), Author (build workflows in dev/test), Approver (approve decisions and prod promotion), Admin (reset, schedules, RBAC). Local users with hashed passwords (argon2 or bcrypt) and signed session tokens; design the auth layer so SSO/identity federation can replace it later. Refuse to start with empty/default admin credentials.
- **Immutable audit:** append-only audit table, each row hash-chained to the previous one, recording who did what, when, from where, before/after (for config changes), with no update or delete path in the code. A `verify-audit` command and endpoint re-checks the chain. Retention is configurable (default 7 years) and nothing deletes audit rows.
- **Human-in-the-loop tasks:** a run **suspends**, a task is assigned to a role, the decision plus reason is recorded, the run **resumes**. Task types: Approval (approve/reject), Manual Match (pair or undo pairing within a run), Data Entry (capture missing inputs), Exception Disposition (resolve unmatched items). Each task has an SLA; a breach raises a notification (in-app plus configurable email/webhook) and shows on an overdue view.
- **SLA and alerting:** per-workflow expected completion time; a breach raises an alert the same way.

### 2. Activity library (each activity = one Python class)
An activity has a name, `category`, a pydantic input schema, and `run(ctx, inputs) -> ActivityResult(outcome, outputs, message, artifacts)`. It never raises to the engine, and returns `failed` with a safe message. **Inputs/outputs are small JSON; big things (spreadsheets, CSVs, tables) go in the run workspace and are passed as file references. Tables between steps are Parquet.** Activities are auto-discovered from an `activities/` package and from a configurable extra folder, with generated docs. Provide `docs/WRITING_AN_ACTIVITY.md` and `activities/_template.py` so a beginner can add one in under 30 lines. Build:
- **gl_query / oracle_query / oracle_execute / oracle_bulk_load:** parametrised SQL with named binds, PL/SQL blocks, chunked `executemany` into staging then MERGE, per-row error reporting. Behind a DB interface with a SQLite implementation so it's testable without Oracle. python-oracledb thin mode.
- **http_request / download_file**, **sftp** (get/put/list), **email** (send via Microsoft Graph with client-secret auth, and SMTP fallback), **graph_read_mail** (newest message since a timestamp from a sender, for OTP), **unc_archive** (copy/move a file to a network path with checksum verification).
- **csv**, **excel**, **zip**, **txt_log** file tools, as in the research notes: streaming and chunked for millions of rows, calamine to read, openpyxl to edit existing workbooks, XlsxWriter for big styled files, pyzipper for AES zips with zip-slip and size caps, declared encodings, read_fwf with `dtype=str`. LibreOffice recalculation is optional and off by default.
- **playwright_robot:** log in to a portal and download a file. Three login styles: API token (no browser), username/password form, and form + **email OTP** (record time before login, poll `graph_read_mail` for a newer message, extract the code with a configurable regex, retry for a fresh code, serialise logins per portal). Save session state in a locked-down folder outside the workspace and reuse until it fails. Also a `playwright_script` variant that runs a team-written Playwright Python script under the same envelope.
- **legacy_robot_wrapper:** wrap an existing standalone Python script/program as an activity ("wrap-first"): run it as a subprocess with args/env from inputs, capture exit code, stdout/stderr (secrets masked) and named output files, map exit codes to outcomes. This is how today's ~15 automations get onto the platform without a rewrite.
- **matching:** a generic two-source matcher (keys, tolerance on amount/date, one-to-one or one-to-many) that outputs matched, unmatched-A and unmatched-B Parquet files and feeds the Manual Match and Exception Disposition tasks.
- **human_task:** creates a task of each type above and suspends the run.
- **ai_extract:** extract fields from a document by calling a configurable internal LLM endpoint with a JSON schema; **off by default** and clearly marked as pending the AI framework approval. Include a fake endpoint for tests.
- **run_python:** run a user script in a separate process with the workspace as its folder. Document that it is process isolation, not a security sandbox.
- Word, PowerPoint and HTML activities are out of scope.

### 3. Robot fabric
Workers are plain Python processes that pull jobs from the bus, resolve the job's secret refs from the secret store for that one call only (passed by stdin/env to the child, never written to the workspace, run records or logs), run the activity, and return the result envelope. Support several workers in parallel on one machine, and a per-run workspace that is a normal folder (so it could later be a shared path). Keep the envelope documented and language-neutral (JSON schema in `docs/ENVELOPE.md`) so a .NET or other worker could implement it later.

### 4. Experience layer (a blend of Microsoft, n8n and Notion)
> **Superseded on 2026-11-06 (DECISIONS 13.1):** the Fluent UI Web Components, Fluent System Icons and the "Microsoft look" below were replaced by WorkTree's own design language: our own Vue components on native elements, warm tokens and Phosphor icons. `docs/design-language.md` is the current source; the rest of this prompt is kept as written.

One **Vue 3 + TypeScript (strict)** single-page app using the Composition API and `<script setup>`, built with Vite and served by FastAPI (commit the built bundle so running the platform doesn't need Node). Stack: Vue Router, Pinia for client state, TanStack Query for Vue (`@tanstack/vue-query`) for server state, `vue-tsc` for type checks, Vitest for unit tests, and **Vue Flow** (`@vue-flow/core`, MIT) for the Studio canvas. For the Microsoft look use Microsoft's **Fluent UI Web Components** (`@fluentui/web-components`, MIT, framework-agnostic so they work in Vue) as the base component set, wrapped in our own thin Vue components; if a needed component is missing there (for example a full-featured data grid), build it ourselves on the same design tokens rather than adding a second UI kit.

**Design direction: take the best of three, copy none of them.** Build our own design tokens, icons and wording; do not reuse any assets, branding or code from n8n, Notion or Microsoft beyond the Fluent UI library itself.
- **Microsoft (structure and enterprise behaviour):** left navigation rail, command bar with the page's primary actions, data grids with sorting/filtering/paging/column chooser, side panels and dialogs for details, message bars and toasts, light/dark/high-contrast themes, full keyboard access (WCAG 2.1 AA target). This is the backbone for the Console, Task Inbox and Admin.
- **n8n (the builder experience):** a canvas of node cards with typed `done`/`failed` ports, a node palette you can search, a properties panel opened by selecting a node, "run this step" on a single node with sample data, and execution data shown on the nodes themselves (green/red state, item counts, durations, click a node to see its inputs and outputs from the last run). Replaying a past run on the canvas read-only is a strong feature to include.
- **Notion (calm, page-like, flexible):** quiet, spacious typography and a light touch of colour; a collapsible sidebar tree grouping workflows by folder/project; every workflow, run and task opens as a "page" with inline-editable title and properties (owner, environment, SLA, tags, description) and a free-text notes/runbook section; a command palette (Ctrl/Cmd+K) to jump anywhere or run an action, and a `/` menu when adding steps or notes; list/table/board views of the same data (for example tasks as a board by status, runs as a table, workflows as a gallery); saved filters and views.
Where the three conflict, apply this order: Microsoft patterns for dense operational data and accessibility, n8n for anything on the canvas, Notion for navigation, page layout and overall feel. Write the choices and tokens in `docs/design-language.md`, build a small set of shared components on top of Fluent (page header, property list, status badge, empty state, run timeline, node card) and use them everywhere so the three styles read as one product. Generate the TypeScript API client from FastAPI's OpenAPI schema so the frontend and backend can't drift (CI fails if the generated client is out of date). For each UI area, study the products listed in `docs/UI_reference_list.md` (rules in "UI references" at the end of this prompt). Pages:
- **Operations Console:** dashboard (counts, running, failed, overdue tasks, recent runs), run history with filters, **run detail** (live step timeline with outcome, duration, masked logs, artifacts with download), Run now with duplicate-guard feedback, schedules, enable/disable.
- **Task Inbox:** my role's tasks, claim/complete with reason, the four task types with sensible forms (including a side-by-side pairing view for Manual Match), SLA countdown, overdue view.
- **Workflow Studio:** a low-code designer that reads and writes the same workflow YAML, with two synchronised views: a Vue Flow canvas (drag activities from a categorised palette, connect `done`/`failed` outcome ports, auto-layout) and a structured step-list/YAML view that stays usable even if someone never touches the canvas. A properties panel generates each activity's input form from its schema (typed fields, validation, dependent fields), lets you map earlier step outputs into inputs via a picker (not just typed expressions), and lets you pick a secret by name from a dropdown (never typing the value). Run a single step on its own with sample inputs, show inline validation errors on the node that causes them, view and diff versions, save a version, and submit for promotion.
- **Admin:** users and roles, environments, secrets metadata (names, last rotated), audit log viewer with chain verification.

### 5. Observability and security
- Structured JSON logs (structlog) with correlation id, rotating files; OpenTelemetry tracing hooks that are off by default.
- Secret masking at every sink (logs, run records, API responses, UI); a test greps for planted secret values.
- A `/health` endpoint and a `/metrics` endpoint (Prometheus text) with run counts and durations.

### 6. Operability
CLI: `serve`, `validate <workflow>`, `run <workflow>`, `list-activities`, `verify-audit`, `create-user`. `config.yaml` with sensible defaults. A `README.md` a new team member can follow from clone to first run.

## Engineering standards (apply to everything above)
- **Typing and linting:** Python fully type-annotated and `mypy --strict` clean; `ruff` (lint + format) clean; TypeScript `strict` with `vue-tsc` and ESLint, and no `any` outside generated code. Pre-commit hooks for all of these. Pin dependencies with a lockfile (`uv.lock` / `package-lock.json`).
- **Structure:** clear layering with dependency direction enforced (API -> services -> domain -> adapters); no business logic in route handlers; dependency injection for DB, bus, secret store, clock and audit so everything is testable. SQLAlchemy 2.x with **Alembic migrations** for every schema change. Pydantic models for every boundary. Async where it pays off, never blocking the event loop (blocking work goes to workers).
- **Contracts:** the job/result envelope and the workflow YAML each have a versioned JSON Schema in `docs/` and **contract tests** that every activity and any future worker must pass. API follows consistent conventions (pagination, error format, idempotency keys on mutating endpoints that triggers might retry).
- **Testing:** unit tests, integration tests against the fakes, and end-to-end tests (Playwright) for the console flows. Property-based tests (Hypothesis) for the workflow validator and the matcher. Coverage gate of at least 85% on `app/`. Tests must be deterministic (injected clock, seeded data) and run in under a few minutes.
- **Security basics even in the MVP:** parameterised SQL only, input validation, secure session cookies/CSRF protection, rate-limit login, argon2id password hashing, no stack traces to clients, dependency audit (`pip-audit`, `npm audit`) in CI, and a threat-model note in `docs/SECURITY.md` listing what is and isn't protected (including that `run_python` and `legacy_robot_wrapper` are process isolation, not sandboxes).
- **Docs:** short architecture decision records in `docs/adr/` for each significant choice, an architecture overview with a diagram, an operations runbook (start, stop, recover, rotate a secret, verify audit), and the extension guides (`WRITING_AN_ACTIVITY.md`, `ENVELOPE.md`).
- **CI:** include a pipeline definition (GitHub Actions style, even if it isn't hosted yet) that runs lint, type checks, tests, the OpenAPI-client freshness check, dependency audit and a production build.
- **Performance and reliability:** budgets from the success targets are asserted in tests; structured error handling and retries have tests for the failure paths, not just the happy path.

## Reference material (Elsa first, n8n second; no dependency on either)
- **Elsa Workflows** (.NET, MIT), the engine the reference .NET design uses and the **major workflow reference for this build**: https://github.com/elsa-workflows (`elsa-core`, `elsa-studio`, `elsa-extensions`, `elsa-guides`, `elsa-gitbook`), docs https://docs.elsaworkflows.io. Model the engine on its concepts (typed inputs/outputs and named outcomes, bookmarks for suspend/resume, per-activity retry strategies, a workflow saved as a reusable activity, and the full list in "Workflow reference model" below).
- **n8n** (TypeScript, fair-code), which Hope knows well, is a **reference for workflow behaviour and builder UX, not just UI**: https://github.com/n8n-io/n8n, docs https://docs.n8n.io, building nodes https://docs.n8n.io/integrations/creating-nodes/. Worth borrowing: one node per tool with an operation dropdown, credential picker, node catalogue, test a single node with pinned data, error-output routing (full list below).
- n8n's Sustainable Use License is not open source: do not copy its code, node definitions, icons or wording and do not depend on it. If anything is ever adapted from Elsa (MIT), keep the notice and record it in `DECISIONS.md`.

## Acceptance: done only when all of this passes
Build realistic **local fixtures** so no production system is needed: a fake portal (login form, email-OTP step, downloadable file), a fake Graph server, a fake SFTP server, a fake LLM endpoint, and SQLite standing in for Oracle.
1. **Standard pattern end to end** (today's shape): portal login with email OTP -> download a password-protected ZIP containing a 1-million-row CSV -> extract -> query the GL (SQLite) -> match against the CSV -> Excel report -> email via fake Graph -> archive to a "UNC" folder with checksum. Peak worker memory stays under 500 MB. Visible live in the console.
2. **Human-in-the-loop:** the matching step leaves unmatched items, the run suspends with an Exception Disposition task, an Operator completes it with a reason, the run resumes and finishes. An overdue task raises an SLA-breach alert.
3. **Segregation of duties:** an Author cannot promote their own workflow; an Approver can; prod refuses an unpromoted version. All tested through the API.
4. **Crash recovery:** kill the service mid-run; on restart the run resumes from the last completed step (and a step marked `resume: restart` re-runs). A hung activity is killed at its timeout and routed through `on_failed`.
5. **Duplicate-run guard** and **dependency trigger** and **file-arrival trigger** each demonstrably work.
6. **Secrets:** no secret value appears in any log, run record, workspace file, API response or UI page (automated grep test). No secret exists outside the secret store.
7. **Audit:** every action above appears in the audit log; the hash chain verifies; tampering with a row is detected by `verify-audit`; there is no code path that updates or deletes audit rows.
8. **Performance:** dashboard endpoint p95 <= 2 s with 5,000 runs seeded; a step event reaches a connected console client within 5 s.
9. **Reuse:** a new workflow that composes existing activities (no new code) is built in the Studio and runs; a legacy script is wrapped with `legacy_robot_wrapper` and runs under the envelope; a new activity dropped in the extra folder appears in the catalogue with no engine changes.
10. Quality gates all pass: `pytest` green with coverage >= 85% on `app/`, `ruff` and `mypy --strict` clean, TypeScript strict build and ESLint clean, the generated API client is up to date, Playwright end-to-end tests cover the console, task inbox and studio flows, every activity has unit tests plus at least one realistic-data test and passes the envelope contract tests, and dependency audits show no known high-severity issues.

## How to work
- Plan the module layout yourself, then build: `app/` (api, services, domain, engine, bus, workers, security, audit, adapters), `activities/`, `web/` (Vue 3 app incl. the Studio), `fixtures/`, `tests/`, `docs/` (with `adr/`).
- Run the code and tests as you go. Don't claim anything works unless you ran it. Anything you can't verify here (real Oracle, real Graph tenant, real portals, real Vault, RabbitMQ) goes in `KNOWN_GAPS.md`, with the interface ready for the real thing.
- Finish with `DECISIONS.md` (choices and why, including every place this version differs from the reference design: Python/FastAPI instead of .NET, own engine instead of Elsa, Fluent web components plus our own design tokens instead of a stock UI kit, adapters instead of Temporal/RabbitMQ/Vault), `KNOWN_GAPS.md`, and a short summary of what runs, what was only tested against fakes, and the exact commands to start it.
- Where `docs/SYSTEM_DESIGN.md` §13 lists an [UNKNOWN] that blocks you (for example YAML key names, the `ctx` API, config key names, the Parquet library), pick the simplest reasonable option and record it in `DECISIONS.md`. Do not wait for an answer.

## Workflow reference model: Elsa first, n8n second (decided 2026-10-22)
Hope's direction: build in Python; **Elsa is the major workflow reference; n8n is also a reference, for workflow behaviour as well as UI.** Make this the first entry in `DECISIONS.md`.

**Precedence when sources disagree:**
1. The explicit text of this prompt.
2. Elsa, for engine and workflow semantics (run model, outcomes, suspend/resume, retries, scheduling, versioning).
3. n8n, for the Studio canvas and builder UX, and for workflow ideas Elsa does not have.
4. `docs/UI_reference_list.md`, for the other UI areas.

**Dependency rules:**
- Do not install, call or run Elsa or n8n.
- Elsa is MIT. If you adapt any of its code, keep the notice and record the adaptation in `DECISIONS.md`.
- Copy nothing from n8n: no code, node definitions, icons or wording.

### Take from Elsa (re-implement each in Python)
Evidence: `docs/HANDOFF.md` §3 and §5, `docs/research/research-14` to `research-18`, https://docs.elsaworkflows.io.

| Elsa concept | Build it as |
|---|---|
| Activity class with `[Input]` / `[Output]` and a category | Activity class with a pydantic input schema, `ActivityResult.outputs` and `category` (for example `Platform / Excel`, `Project X / ...`) |
| `[Activity]` version | A `version` on every activity. Workflow versions record which activity versions they used. |
| Named outcomes drawn as Flowchart connections | `on_done` / `on_failed` routing on the canvas, one port per outcome |
| No Try/Catch, so nodes complete with a "Failed" outcome | Activities never raise. They return `failed` with a safe message. |
| Incidents (fault the workflow, or continue with incidents) | Any unexpected engine-side error is recorded as an incident on the run. Default: fault the run. |
| Bookmarks (suspend, persist, resume by token) | A suspended run stores a resume token in the DB. `human_task` completion and waiting triggers resume it. Suspension survives restarts. |
| Resilience strategies, with each attempt recorded | `retries` (count, delay, backoff) per step. Every attempt is recorded on the step and shown in run detail. |
| Alterations "retry faulted instance" | A "Retry from failed step" action for Operators, audited. This closes the "re-runs need server access" gap. |
| Scheduler rebuilt from stored triggers; past-due runs staggered | On startup, rebuild all schedules from the DB. Runs with `catch_up: true` are staggered, not fired in a burst. |
| `LogPersistenceMode` (include/exclude activity I/O) | A per-workflow/per-step setting for what goes into run records. Default: small JSON only, never secret values or bulk data. |
| Workflow "usable as activity", pinned to a version, flagged when a newer one exists | A sub-workflow step pins a version. Studio shows "newer version available". |
| Secret picker, `CanContainSecrets` | Secret dropdown in the properties panel. Sensitive inputs are masked everywhere. |
| `RefreshOnChange` option providers | Dependent fields: an API endpoint recomputes a field's options from the other fields' current values (for example sheet names after choosing a file). |
| `ActivityTestRunner` with test values | "Run this step" with sample inputs. Also pin upstream data, as in the n8n list below. |
| `UserTask` | `human_task` |

Do not copy these known Elsa weak spots (`docs/research/research-17`, `research-18`):
- a static encryption key for secrets;
- user code running in the engine process;
- large non-serializable outputs passed through variables;
- a single-node test with no upstream data;
- data mapping by typed expressions only (build the output picker);
- no catch-all error route.

### Take from n8n (workflow behaviour and UX)
Evidence: `docs/research/research-14`, `research-15`, https://docs.n8n.io.

**Workflow behaviour:**
- One node per tool. `csv`, `excel`, `zip`, `txt_log` and `sftp` are each one activity with a Resource/Operation pair of dropdowns, and the fields shown depend on the operation (the n8n `displayOptions` idea). The gl/oracle activities stay as listed above.
- Credentials are chosen from saved connections, never typed.
- A searchable node catalogue, generated from the activity registry.
- Error output: every node has a `failed` port that can be wired.
- A separate code node for anything the operations do not cover: `run_python`.
- Files travel by reference, never in memory or JSON. The run workspace must be able to become shared storage once workers run on several machines.

**UX:**
- Node cards with typed `done` / `failed` ports.
- A node details view with input data, settings and output data side by side.
- Execution data on the nodes: state, item counts, durations.
- Read-only replay of a past run on the canvas.
- Pin data: when testing one step, reuse the upstream outputs from the last run (editable) instead of empty inputs.

### UI references
`docs/UI_reference_list.md` names reference products for 9 areas: app shell, operations dashboard, run detail, Studio canvas, node properties, Task Inbox, data views, page-like detail, and admin/audit.
- Use each product only for the area it is listed under.
- Resolve conflicts with the order in section 4: Microsoft for dense operational data and accessibility, n8n for the canvas, Notion for navigation, page layout and feel.
- Take patterns only. Use no assets, branding, icons, code or wording from any listed product. (Superseded 2026-11-06, DECISIONS 13.1: no UI library is used; icons are Phosphor, MIT, copied by a generator.)
- Record the chosen pattern per area in `docs/design-language.md`.
