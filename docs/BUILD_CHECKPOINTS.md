# BUILD_CHECKPOINTS: UAF Python/FastAPI MVP

The complete, ordered list of build checkpoints for `docs/BUILD_PROMPT_python_mvp.md`. Progress against this list is tracked in `BUILD_PROGRESS.md` at the repository root.

## What a checkpoint is (and is not)
- A checkpoint is a **progress and resume marker**: a named point with a verifiable "Done when" test and a git commit. If the build is interrupted, the agent reads `BUILD_PROGRESS.md`, finds the current checkpoint, and continues from there.
- A checkpoint is **not a stage or phase**. Do not stop, pause, summarise for approval or ask for confirmation at a checkpoint boundary. Commit, update the tracker, and go straight to the next one. This keeps the rule "build the whole thing as one coherent piece, not in stages" (`BUILD_PROMPT:3`; `HANDOFF:14`).
- The order is the dependency order. You may run ahead on an independent checkpoint while one is blocked. Mark that in the tracker.
- **IDs are permanent.** Never renumber. If a new checkpoint is needed, insert it with a letter suffix (for example `CP-14a`) and add it to the tracker.
- "Done when" items must be **run**, not assumed (`BUILD_PROMPT:121`). Record the command and the result in the tracker.
- Anything that cannot be verified here (real Oracle, Graph tenant, portals, Vault, RabbitMQ) is done against the fakes. Log the gap in `KNOWN_GAPS.md`.

Abbreviations: `BP` = `docs/BUILD_PROMPT_python_mvp.md`; `SD` = `docs/SYSTEM_DESIGN.md`; `A1`…`A10` = acceptance items `BP:108-117`.

## Summary

| ID | Title | Spec |
|---|---|---|
| CP-00 | Bootstrap: git, tracker, baseline commit | this file |
| CP-01 | Repository skeleton and Python tooling | BP:92-93,120 |
| CP-02 | Configuration, settings and injected clock | BP:89,93 |
| CP-03 | Structured logging, correlation id, secret masking | BP:84-85 |
| CP-04 | Database layer and first Alembic migration | BP:37,93 |
| CP-05 | Immutable hash-chained audit | BP:50 |
| CP-06 | Secret store interface and adapters | BP:34,37,68 |
| CP-07 | Authentication, sessions and RBAC | BP:49,96 |
| CP-08 | Workflow definition schema and validator | BP:43,94-95 |
| CP-09 | Version registry, environments, promotion and SoD | BP:44 |
| CP-10 | Job/result envelope contract | BP:47,68,94 |
| CP-11 | Activity framework, registry and discovery | BP:55; BP:139-166 |
| CP-12 | Message bus interface and adapters | BP:29,37 |
| CP-13 | Worker runtime | BP:47,68 |
| CP-14 | Run engine | BP:43,47; BP:139-166 |
| CP-15 | Durable resume, suspension and crash recovery | BP:47,51 |
| CP-16 | Triggers, scheduler and duplicate-run guard | BP:45-46,94 |
| CP-17 | Human tasks, SLA and alerting | BP:51-52 |
| CP-18 | REST API completion, live events, health and metrics | BP:42,48,86,94 |
| CP-19 | Local fixtures (fake portal, Graph, SFTP, LLM, GL) | BP:107 |
| CP-20 | Activities: GL and Oracle | BP:56 |
| CP-21 | Activities: HTTP, download, SFTP, UNC archive | BP:57 |
| CP-22 | Activities: email and Graph mail | BP:57 |
| CP-23 | Activities: file tools (csv, excel, zip, txt_log) | BP:58; BP:168-178 |
| CP-24 | Activities: Playwright robot and script | BP:59 |
| CP-25 | Activities: legacy wrapper and run_python | BP:60,64 |
| CP-26 | Activities: matching, human_task, ai_extract | BP:61-63 |
| CP-27 | Frontend foundation and design language | BP:71-77 |
| CP-28 | App shell, navigation and command palette | BP:74,76; UI list 1-4 |
| CP-29 | Operations Console | BP:78; UI list 6-14 |
| CP-30 | Task Inbox | BP:79; UI list 26-29 |
| CP-31 | Workflow Studio | BP:75,80; UI list 16-24 |
| CP-32 | Admin | BP:81; UI list 41-44 |
| CP-33 | Pages, data views and saved views | BP:76; UI list 31-39 |
| CP-34 | Acceptance A1: standard pattern end to end | A1 |
| CP-35 | Acceptance A2, A6, A7: HITL, secrets, audit | A2, A6, A7 |
| CP-36 | Acceptance A3, A4, A5: SoD, crash recovery, triggers | A3, A4, A5 |
| CP-37 | Acceptance A8, A9: performance and reuse | A8, A9 |
| CP-38 | End-to-end browser tests | BP:95,117 |
| CP-39 | Security hardening and threat model | BP:96 |
| CP-40 | CI pipeline and quality gates | BP:92,98 |
| CP-41 | Documentation set | BP:89,97,122 |
| CP-42 | Final verification (A10) and handover | A10; BP:122 |

---

## Checkpoint details

### CP-00 Bootstrap: git, tracker, baseline commit
- **Build:**
  - `git init` (local only).
  - Set a repo-local identity only if none is configured: `git config user.name "UAF Build Agent"`, `git config user.email "uaf-build-agent@localhost"`.
  - Create `.gitignore`: `.venv/`, `__pycache__/`, `node_modules/`, `*.db`, `*.sqlite*`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `coverage*`, the runtime data folder (workspaces, logs, Playwright session state), and generated large fixtures. Do **not** ignore the built web bundle (BP:71).
  - Fill in the header of `BUILD_PROGRESS.md`.
- **Done when:** `git log` shows a baseline commit containing all existing docs and the `.pptx`, and `git status` is clean.
- **Commit:** `cp-00: bootstrap repository and progress tracker`

### CP-01 Repository skeleton and Python tooling
- **Build:**
  - `pyproject.toml` managed by uv, with `uv.lock`. Python 3.11+. If a dependency lacks wheels for the installed Python, use a uv-managed 3.12 and record it in `DECISIONS.md`.
  - Packages `app/{api,services,domain,engine,bus,workers,security,audit,adapters}`, plus `activities/`, `web/`, `fixtures/`, `tests/{unit,integration,e2e,contract}`, `docs/adr/`.
  - ruff (lint + format), mypy `--strict`, pytest + coverage, Hypothesis, pre-commit hooks.
  - An import-layering check that enforces API → services → domain → adapters (for example import-linter).
  - Create `DECISIONS.md`. Its first entry is the reference model (Elsa first, n8n second; BP:125-137). Also create `KNOWN_GAPS.md`, `LICENSES.md` and a stub `README.md`.
- **Done when:** `uv sync`, `ruff check .`, `ruff format --check .`, `mypy --strict app activities`, `pytest`, the layering check and `pre-commit run --all-files` all pass.
- **Commit:** `cp-01: project skeleton, tooling and layering rules`

### CP-02 Configuration, settings and injected clock
- **Build:**
  - `config.yaml` with sensible defaults, and a typed settings model (pydantic-settings). Config holds no secret values.
  - Settings for: DB URL, data/workspace root, Playwright session-state folder (outside workspaces), extra activities folder, audit retention (default 7 years), AI endpoint + enabled flag (off), OTel flag (off), worker count, bus adapter, secret-store adapter.
  - A `Clock` interface with system and fake implementations.
  - A DI container or provider functions for DB, bus, secret store, clock and audit (BP:93).
- **Done when:** unit tests load defaults, apply an override file and env overrides, and reject invalid values.
- **Commit:** `cp-02: configuration, settings and clock`

### CP-03 Structured logging, correlation id, secret masking
- **Build:**
  - structlog JSON to rotating files and the console.
  - A correlation id bound per request, run and step.
  - A masking processor that redacts every value currently known to the secret store.
  - OpenTelemetry hooks, off by default.
- **Done when:** a test logs a planted secret and asserts it never appears in the log file, and every log line carries a correlation id.
- **Commit:** `cp-03: structured logging, correlation id, masking`

### CP-04 Database layer and first Alembic migration
- **Build:**
  - SQLAlchemy 2.x models and the Alembic baseline for: users, roles, user_roles, sessions, workflows, workflow_versions, environments, promotions, schedules/triggers, runs, run_steps, step_attempts, incidents, resume tokens (bookmarks), tasks, task_events, artifacts, secrets_metadata, audit_log, notifications, saved_views, idempotency_keys.
  - Indexes for the dashboard queries (BP:48).
  - A DB interface with a SQLite default. Oracle is configurable via python-oracledb thin mode, and its dialect differences are documented.
  - Record the chosen table and column names in `docs/` and `DECISIONS.md`. They close the gap in SD §6.5.
- **Done when:** `alembic upgrade head` and `alembic downgrade base` both run on SQLite, and repository tests pass.
- **Commit:** `cp-04: database models and baseline migration`

### CP-05 Immutable hash-chained audit
- **Build:**
  - An append-only audit writer. Each row stores the previous row's hash, who, what, when, from where, and before/after for config changes.
  - A `verify-audit` CLI command and API endpoint.
  - A retention setting. Nothing deletes audit rows.
- **Done when:**
  - The chain verifies after N writes.
  - Tampering with a row is detected.
  - A test fails if any code path issues UPDATE or DELETE on `audit_log` (static grep plus an ORM event guard).
- **Commit:** `cp-05: hash-chained append-only audit`

### CP-06 Secret store interface and adapters
- **Build:**
  - A `SecretStore` interface (resolve by name, list metadata, never list values).
  - Default implementation: env vars + optional config file. Optional HashiCorp Vault adapter (hvac).
  - A secrets-metadata API: names and last-rotated date only.
  - Resolution happens only inside the worker, per call (BP:68).
  - Register resolved values with the masking processor.
- **Done when:** unit tests cover resolve, missing secret and metadata, and no API response or log contains a value.
- **Commit:** `cp-06: secret store and adapters`

### CP-07 Authentication, sessions and RBAC
- **Build:**
  - Local users with argon2id hashes, signed session cookies, CSRF protection and login rate-limiting.
  - Roles Viewer, Operator, Author, Approver, Admin, and a permission matrix in the service layer.
  - A `create-user` CLI command. The `serve` command refuses to start with empty or default admin credentials.
  - The auth layer sits behind an interface so SSO can replace it.
  - Audit login and role changes.
- **Done when:** API tests cover each role's allowed and denied actions, the rate limit, CSRF rejection, and the refusal to start.
- **Commit:** `cp-07: authentication, sessions and RBAC`

### CP-08 Workflow definition schema and validator
- **Build:**
  - Pydantic models and a versioned JSON Schema in `docs/` for the workflow YAML/JSON. Steps have `id`, the activity type, `inputs` with `{{ steps.x.y }}` and `{{ secret:name }}` references, `on_done`/`on_failed`, `timeout_seconds`, `retries`, `resume`, `foreach` over small lists, and sub-workflow calls with a pinned version.
  - Also per-workflow settings: `catch_up`, duplicate-guard mode and key, SLA, persistence settings, owner, tags.
  - A validator that reports an unknown activity, a bad reference, an unreachable step or a cycle, with clear messages.
  - A `validate <workflow>` CLI command.
- **Done when:** unit tests plus Hypothesis property tests for the validator pass, and the schema file exists.
- **Commit:** `cp-08: workflow schema and validator`

### CP-09 Version registry, environments, promotion and SoD
- **Build:**
  - Every save creates an immutable version.
  - Environments `dev`, `test`, `prod`. Promotion dev → test → prod needs an Approver decision. An Author cannot promote their own workflow. Prod runs only promoted versions.
  - Version diff data for the Studio.
  - All of it audited.
- **Done when:** API tests prove the SoD rules (A3 preconditions) and that prod refuses an unpromoted version.
- **Commit:** `cp-09: version registry, promotion and segregation of duties`

### CP-10 Job/result envelope contract
- **Build:**
  - `docs/ENVELOPE.md` and a versioned JSON Schema. In: `{run_id, step_id, activity, inputs, secret_refs, workspace}` plus correlation id and schema version. Out: `{outcome: done|failed, outputs, message, artifacts}`.
  - Pydantic models.
  - A reusable contract-test suite that every activity (and any future worker) must pass.
- **Done when:** the contract tests run against a dummy activity and the schema validates the sample envelopes.
- **Commit:** `cp-10: job/result envelope contract`

### CP-11 Activity framework, registry and discovery
- **Build:**
  - An activity base class with `name`, `category` (for example `Platform / Excel`), `version` and a pydantic input schema, and `run(ctx, inputs) -> ActivityResult`. Activities never raise: the framework converts any exception into `failed` with a safe message.
  - Fields flagged sensitive.
  - Dependent-field option providers (the Elsa `RefreshOnChange` idea).
  - Auto-discovery from `activities/` and the configured extra folder.
  - A `list-activities` CLI command and generated activity docs.
  - `activities/_template.py` (a new activity in under 30 lines) and `docs/WRITING_AN_ACTIVITY.md`.
- **Done when:** a file dropped into the extra folder appears in `list-activities` with no engine change, and the template activity passes the contract tests.
- **Commit:** `cp-11: activity framework and discovery`

### CP-12 Message bus interface and adapters
- **Build:**
  - A bus interface.
  - Default: a durable DB-backed queue with visibility timeout, retries and dead-letter.
  - Optional RabbitMQ adapter (aio-pika). Test it only if available; otherwise log it in `KNOWN_GAPS.md`.
- **Done when:** integration tests cover enqueue, claim, ack, retry, redelivery after a simulated crash, and no double processing.
- **Commit:** `cp-12: message bus`

### CP-13 Worker runtime
- **Build:**
  - Worker processes that pull jobs.
  - Each job resolves `secret_refs` for one call and passes them to a child process by stdin/env.
  - The activity runs in a separate OS process with a timeout, and the whole process tree is killed on timeout.
  - The worker returns the result envelope and supports several workers in parallel.
  - A crashed or hung worker never affects the control plane.
- **Done when:** integration tests cover the timeout kill (including grandchild processes), a crash, parallel jobs, and secrets absent from the workspace and run records.
- **Commit:** `cp-13: worker runtime`

### CP-14 Run engine
- **Build:**
  - Run creation with a run id, correlation id and per-run workspace.
  - Step dispatch through the bus. Outcome routing via `on_done`/`on_failed`.
  - Retries with backoff, with each attempt recorded.
  - `foreach`. Sub-workflow steps that run a pinned version.
  - Incidents recorded on the run (default: fault the run).
  - Per-workflow/per-step persistence settings: small JSON only, never secrets or bulk data.
  - Run state persisted after every step, and audited.
- **Done when:** integration tests run multi-step, branching, retrying, foreach and sub-workflow cases against fake activities.
- **Commit:** `cp-14: run engine`

### CP-15 Durable resume, suspension and crash recovery
- **Build:**
  - On startup, resume interrupted runs from the last completed step. Honour `resume: restart|skip`.
  - Suspension through resume tokens (bookmarks) that survive restarts.
  - An Operator "Retry from failed step" action, audited.
- **Done when:** a test kills the service process mid-run and restarts it, the run resumes correctly, and a `resume: restart` step re-runs (A4 core).
- **Commit:** `cp-15: durable resume and crash recovery`

### CP-16 Triggers, scheduler and duplicate-run guard
- **Build:**
  - Cron with APScheduler. Schedules are rebuilt from the DB on startup. Missed runs are skipped by default; `catch_up: true` runs are staggered.
  - Webhook triggers with a per-workflow token.
  - File-arrival triggers (watch a folder/UNC path; settle time; process each file once).
  - Manual "Run now".
  - Dependency triggers (another workflow ends with a given outcome).
  - The duplicate-run guard rejects or queues a second trigger and records the reason.
  - Idempotency keys on mutating endpoints.
- **Done when:** tests with an injected clock cover cron and catch-up, the webhook token, file arrival, the dependency trigger and the guard (A5 core).
- **Commit:** `cp-16: triggers, scheduler and duplicate-run guard`

### CP-17 Human tasks, SLA and alerting
- **Build:**
  - The task service: Approval, Manual Match (pair and undo within a run), Data Entry, and Exception Disposition.
  - Assignment to a role, claim, and complete with a reason. Completion resumes the run.
  - A task SLA with breach detection, notifications (in-app plus configurable email/webhook) and an overdue query.
  - Workflow-level SLA (expected completion time) alerts.
- **Done when:** integration tests cover suspend → complete → resume, and an injected-clock test raises an SLA breach.
- **Commit:** `cp-17: human tasks, SLA and alerting`

### CP-18 REST API completion, live events, health and metrics
- **Build:**
  - Every resource in BP:42, with consistent pagination, error format and idempotency.
  - OpenAPI enabled, and no stack traces returned to clients.
  - WebSocket (or SSE) step events.
  - `/health`, and `/metrics` in Prometheus text format.
  - The dashboard endpoint.
  - The `serve` and `run <workflow>` CLI commands.
- **Done when:** API tests cover every resource, a step event reaches a test client, and the OpenAPI schema is exported to a file for client generation.
- **Commit:** `cp-18: API, live events, health and metrics`

### CP-19 Local fixtures
- **Build** under `fixtures/`, each runnable as a local server:
  - a fake portal (login form, email-OTP step, file download, an API-token mode);
  - a fake Graph server (token endpoint, list messages with `$filter`/`$orderby`, sendMail, upload);
  - a fake SFTP server;
  - a fake LLM endpoint;
  - a SQLite GL database.
  - Data generators: a 1M-row CSV inside an AES-256 ZIP, Excel samples, and fixed-width and log files.
  - Generated big files are produced at test time and git-ignored.
- **Done when:** each fixture starts and stops from pytest fixtures, and a smoke test passes for each.
- **Commit:** `cp-19: local fixtures`

### CP-20 Activities: GL and Oracle
- **Build:**
  - `gl_query`, `oracle_query`, `oracle_execute` (PL/SQL blocks) and `oracle_bulk_load`. The bulk load does a chunked `executemany` into staging, then a MERGE, with per-row error reporting.
  - Named binds only. A DB interface with a SQLite implementation.
- **Done when:** unit and realistic-data tests on SQLite pass, the activities pass the contract tests, and the real-Oracle gap is logged.
- **Commit:** `cp-20: GL and Oracle activities`

### CP-21 Activities: HTTP, download, SFTP, UNC archive
- **Build:** `http_request`; `download_file` (streamed to the workspace); `sftp` as one node with get/put/list operations; `unc_archive` (copy/move to a network path with checksum verification).
- **Done when:** tests against the fixtures pass, including a checksum mismatch → `failed`.
- **Commit:** `cp-21: HTTP, download, SFTP and archive activities`

### CP-22 Activities: email and Graph mail
- **Build:**
  - `email`: Graph sendMail with client-secret auth, and an SMTP fallback.
  - `graph_read_mail`: the newest message after a timestamp from a given sender, using a `$select` that keeps responses small.
- **Done when:** tests against the fake Graph and a local SMTP sink pass, and the real-tenant gap is logged.
- **Commit:** `cp-22: email and Graph mail activities`

### CP-23 Activities: file tools
- **Build** `csv`, `excel`, `zip` and `txt_log`, each one node with a Resource/Operation dropdown and per-operation fields (the n8n idea):
  - streaming or chunked processing;
  - python-calamine to read, openpyxl to edit, XlsxWriter for large styled output;
  - pyzipper for AES zips, with zip-slip protection and size/count caps;
  - declared encodings, and `read_fwf(dtype=str)`;
  - tables between steps written as Parquet.
  - LibreOffice recalculation is optional and off by default.
- **Done when:**
  - Every operation has unit tests plus a realistic-data test.
  - Processing the 1M-row CSV stays under 500 MB peak worker memory (measured).
  - A zip-bomb sample and a zip-slip sample are rejected.
- **Commit:** `cp-23: file tool activities`

### CP-24 Activities: Playwright robot and script
- **Build:**
  - `playwright_robot` with three login styles: API token, form, and form + email OTP. For OTP: record T0, poll `graph_read_mail`, extract the code with a configurable regex, retry for a fresh code, and serialise logins per portal.
  - Session state saved in the locked-down folder outside workspaces, and reused until it fails.
  - `playwright_script`, which runs a team-written script under the envelope.
- **Done when:** tests against the fake portal pass for all three styles, plus stale-code and expired-session cases.
- **Commit:** `cp-24: Playwright activities`

### CP-25 Activities: legacy wrapper and run_python
- **Build:**
  - `legacy_robot_wrapper`: runs a subprocess with args/env from inputs, maps exit codes to outcomes, captures stdout/stderr with secrets masked, and collects named output files.
  - `run_python`: runs a user script in a separate process with the workspace as its folder. Document that this is process isolation, not a sandbox.
- **Done when:** a sample legacy script runs under the envelope, and a masking test passes.
- **Commit:** `cp-25: legacy wrapper and run_python`

### CP-26 Activities: matching, human_task, ai_extract
- **Build:**
  - `matching`: two sources, keys, amount/date tolerance, 1:1 or 1:N. Outputs matched, unmatched-A and unmatched-B as Parquet.
  - `human_task`: creates each task type and suspends the run.
  - `ai_extract`: calls the configurable internal endpoint with a JSON schema. Off by default and marked as pending AI-framework approval.
- **Done when:** Hypothesis tests for the matcher pass, human_task suspends and resumes, and ai_extract passes against the fake LLM and is refused when disabled.
- **Commit:** `cp-26: matching, human_task and ai_extract`

### CP-27 Frontend foundation and design language
- **Build:**
  - `web/` with Vite, Vue 3 + TypeScript strict, `<script setup>`, Vue Router, Pinia, `@tanstack/vue-query`, `@vue-flow/core` and `@fluentui/web-components` wrapped in our own thin Vue components.
  - Design tokens, light/dark/high-contrast themes, our own icons.
  - Shared components: page header, property list, status badge, empty state, run timeline, node card.
  - A TS client generated from the OpenAPI file, with a freshness check script.
  - `docs/design-language.md`, recording the chosen pattern per area from `docs/UI_reference_list.md`.
  - The built bundle is served by FastAPI and committed.
- **Done when:** `vue-tsc`, ESLint (no `any` outside generated code) and Vitest pass, `npm run build` output is served by `serve`, and the client freshness check passes.
- **Commit:** `cp-27: frontend foundation and design language`

### CP-28 App shell, navigation and command palette
- **Build:**
  - Left nav rail, breadcrumbs, a collapsible sidebar tree (workflows by folder/project), a command bar per page, and a Ctrl/Cmd+K command palette.
  - Login page, message bars and toasts.
  - Full keyboard access (WCAG 2.1 AA target).
- **Done when:** Vitest component tests pass and keyboard navigation works across the shell.
- **Commit:** `cp-28: app shell and command palette`

### CP-29 Operations Console
- **Build:**
  - A dashboard (counts, running, failed, overdue tasks, recent runs).
  - Run history with filters.
  - Run detail: a live step timeline with outcomes, durations, retry attempts and incidents, masked logs, and artifact download.
  - "Run now" with duplicate-guard feedback, "Retry from failed step", and schedules with enable/disable.
- **Done when:** component tests pass, and manual verification with a running server shows live updates within 5 s.
- **Commit:** `cp-29: operations console`

### CP-30 Task Inbox
- **Build:**
  - My role's tasks as a list and a board.
  - Claim and complete with a reason, with forms for the four task types, including a side-by-side Manual Match pairing view.
  - An SLA countdown and an overdue view.
- **Done when:** component tests pass, and a manual end-to-end check completes a task and resumes its run.
- **Commit:** `cp-30: task inbox`

### CP-31 Workflow Studio
- **Build:**
  - A Vue Flow canvas: a searchable categorised palette, node cards with `done`/`failed` ports, and auto-layout.
  - A synchronised step-list/YAML view.
  - A properties panel generated from the activity schema: typed fields, Resource/Operation dropdowns with dependent fields, an output picker for earlier steps, and a secret dropdown.
  - Inline validation errors on the node that causes them.
  - "Run this step" with sample inputs and **pinned upstream data** from the last run.
  - Execution data on nodes (state, counts, durations). Read-only replay of a past run.
  - Version list and diff, save version, submit for promotion, and a "newer version available" flag on sub-workflow nodes.
- **Done when:**
  - Component tests pass.
  - A workflow built on the canvas round-trips to YAML and back unchanged.
  - The YAML view alone can author a valid workflow.
- **Commit:** `cp-31: workflow studio`

### CP-32 Admin
- **Build:** users and roles, environments, secrets metadata (names and last-rotated date, never values), and an audit log viewer with search, filters and chain verification.
- **Done when:** component tests pass, and role restrictions are enforced in both the UI and the API.
- **Commit:** `cp-32: admin`

### CP-33 Pages, data views and saved views
- **Build:**
  - Workflow, run and task pages with an inline-editable title, properties (owner, environment, SLA, tags, description), notes/runbook, and an activity feed.
  - Table, board and gallery views of the same data, with saved filters and views.
  - A `/` menu when adding steps or notes.
- **Done when:** component tests pass and saved views persist through the API.
- **Commit:** `cp-33: pages and data views`

### CP-34 Acceptance A1: standard pattern end to end
- **Build:** the reference workflow YAML in `examples/`. Flow: portal login with email OTP → download the AES ZIP → extract the 1M-row CSV → GL query → match → Excel report → email via fake Graph → archive with checksum.
- **Done when:** an automated test runs it to `done`, peak worker memory is under 500 MB (measured and recorded), and the run is visible live in the console.
- **Commit:** `cp-34: acceptance A1 standard pattern`

### CP-35 Acceptance A2, A6, A7: HITL, secrets, audit
- **Done when:**
  - **A2:** unmatched items → an Exception Disposition task → an Operator completes it with a reason → the run resumes and finishes, and an overdue task raises an SLA alert.
  - **A6:** an automated grep for planted secret values over logs, run records, workspace files, API responses and rendered UI pages finds nothing.
  - **A7:** every action appears in the audit log, the chain verifies, tampering is detected, and no update/delete path exists.
- **Commit:** `cp-35: acceptance A2, A6, A7`

### CP-36 Acceptance A3, A4, A5: SoD, crash recovery, triggers
- **Done when:**
  - **A3:** API tests for SoD pass.
  - **A4:** kill the service mid-run → it resumes. A `resume: restart` step re-runs. A hung activity is killed at its timeout and routed through `on_failed`.
  - **A5:** the duplicate-run guard, the dependency trigger and the file-arrival trigger each work in automated tests.
- **Commit:** `cp-36: acceptance A3, A4, A5`

### CP-37 Acceptance A8, A9: performance and reuse
- **Done when:**
  - **A8:** with 5,000 runs seeded, the dashboard p95 is ≤ 2 s and a step event reaches the client in ≤ 5 s. Both are asserted in tests.
  - **A9:** a new workflow composed only from existing activities is built in the Studio and runs. A legacy script runs via `legacy_robot_wrapper`. A new activity dropped into the extra folder appears in the catalogue with no engine change.
- **Commit:** `cp-37: acceptance A8, A9`

### CP-38 End-to-end browser tests
- **Build:** Playwright E2E tests for the console, task inbox and studio flows (login, run now, live timeline, complete a task, build and save a workflow, single-step run, promotion request).
- **Done when:** the E2E suite passes headless against a locally started server and fixtures.
- **Commit:** `cp-38: end-to-end browser tests`

### CP-39 Security hardening and threat model
- **Build:**
  - `docs/SECURITY.md`: a threat model of what is and is not protected. `run_python` and `legacy_robot_wrapper` are process isolation, not sandboxes.
  - Verify parameterised SQL everywhere, input validation, secure cookies/CSRF, the login rate limit, no stack traces, and argon2id.
  - `pip-audit` and `npm audit` show no known high-severity issues.
- **Done when:** the security tests and both audits pass. Any accepted findings go in `KNOWN_GAPS.md` with a reason.
- **Commit:** `cp-39: security hardening`

### CP-40 CI pipeline and quality gates
- **Build:** a `.github/workflows/ci.yml` (not hosted) that runs ruff, mypy `--strict`, pytest with coverage ≥ 85% on `app/`, vue-tsc, ESLint, Vitest, the OpenAPI client freshness check, pip-audit, npm audit and a production build. Pre-commit runs the same checks locally.
- **Done when:** every CI step passes when run locally in sequence (record the commands).
- **Commit:** `cp-40: CI pipeline and gates`

### CP-41 Documentation set
- **Build:**
  - `README.md`: clone to first run, for a new team member.
  - An architecture overview with a diagram, and ADRs in `docs/adr/` for each significant choice.
  - An operations runbook: start, stop, recover, rotate a secret, verify audit.
  - Final versions of `docs/ENVELOPE.md`, `docs/WRITING_AN_ACTIVITY.md`, `LICENSES.md`, `DECISIONS.md` (including every difference from the reference design) and `KNOWN_GAPS.md`.
  - Update `docs/SYSTEM_DESIGN.md`: change [SPEC] items that now exist into facts with code citations.
- **Done when:** a fresh clone, following only `README.md`, reaches a running console (verified in a temporary directory).
- **Commit:** `cp-41: documentation set`

### CP-42 Final verification (A10) and handover
- **Build:**
  - Run every gate in A10 from a clean state.
  - Write the final summary in `BUILD_PROGRESS.md`: what runs, what was only tested against fakes, and the exact start commands.
  - Tag `mvp-complete` (local tag).
- **Done when:** all A1-A10 items are green and recorded, and `git status` is clean.
- **Commit:** `cp-42: final verification and handover`
