# BUILD_PROGRESS: UAF Python/FastAPI MVP

The resume point for the build agent. **Read this file first on every start or restart.** Checkpoint definitions are in `docs/BUILD_CHECKPOINTS.md`. Process rules are in `docs/AGENT_START_PROMPT.md`.

## Current position
- **Current checkpoint:** CP-15
- **Status:** in-progress (verifying existing code checkpoint by checkpoint)
- **Next action:** CP-15: crash-recovery test (kill mid-run, restart, resume; `resume: restart|skip`).
- **Last commit:** see `git log -1`.
- **Last updated:** 2026-10-23

## Verification snapshot (run, not assumed)

| Gate | Command | Result |
|---|---|---|
| Tests | `uv run pytest -q` | **98 passed** |
| Lint | `uv run ruff check .` | passed |
| Format | `uv run ruff format --check .` | passed (127 files) |
| Types | `uv run mypy --strict app activities fixtures` | passed (80 source files) |
| Layering | `uv run lint-imports` | passed (1 contract kept) |
| Hooks | `uv run pre-commit run --all-files` | all hooks passed |
| Migrations | `alembic upgrade head` / `downgrade base` / `upgrade head` / `alembic check` (scratch SQLite) | passed; "No new upgrade operations detected" |

**Not yet verified:** coverage percentage; worker timeout/grandchild-kill tests; trigger webhook/file/dependency tests; activity-library fixture tests; Playwright; the whole frontend; acceptance items A1-A10.

## Code review (2026-10-22, build-3)

Full review of the backend before closing CP-01. Every item below is fixed and has a regression test in `tests/integration/test_review_regressions.py` or `tests/integration/test_bus.py` unless noted.

| # | Defect | Fix |
|---|---|---|
| R1 | `test_yaml_round_trip...` expected `yaml.YAMLError`; the loader correctly raises `ValidationFailed` (suite was red: 25/26) | test corrected |
| R2 | Failure envelopes (timeout, missing secret, child crash, unknown activity) dropped `iteration`, so a failed foreach item was reported against item 0 | `ResultEnvelope.failure()` keeps run/step/iteration |
| R3 | Bus visibility timeout (300 s) shorter than the allowed activity timeout (up to 24 h): long steps were redelivered and ran twice | per-job lease extended to timeout + 60 s; release by lease end |
| R4 | `recover()` and the watchdog re-dispatched a step while its original job stayed on the bus (double execution); an acked result whose callback failed stranded the run; dead-lettered jobs stranded the step | `bus_job_id` + `attempt` on jobs; orphan release on startup; reconcile/cancel in `_check_dispatched` (DECISIONS 6.6, 6.9) |
| R5 | Audit hash chain forked under concurrent transactions (tail read before taking the write lock) | `audit_head` lock row (DECISIONS 9.1); 6-thread test verifies the chain |
| R6 | Scheduler tick and worker callbacks mutated the same runs concurrently | engine `RLock` (DECISIONS 6.10) |
| R7 | Human-task completion resumed the latest open token, not the one for the completed task | token matched by `task_id` |
| R8 | `app/main.py` built a full container at import time (created `runtime/uaf.db`) | module-level `app` removed (DECISIONS 9.8) |
| R9 | Failed logins were never audited (audit row rolled back with the 401) | route commits before re-raising |
| R10 | Cancel left open tasks actionable; "retry from failed step" could pick the wrong step | engine `cancel_run` (jobs, tasks, child runs) and `retry_from_failed_step` |
| R11 | `catch_up` cron fired the same slot forever; missed fires were never skipped | strict-after cron, misfire grace (DECISIONS 9.4) |
| R12 | SoD: prod ran unpromoted older versions; prod promotion accepted any version below a test-approved one | exact-version checks (DECISIONS 9.3) |
| R13 | **Security:** `requires_admin_author` was never enforced; an Author could save `run_python` (server code execution) | Admin-only save (DECISIONS 9.2) |
| R14 | `human_task` input types (`exception`, `review`) did not match the task service types, so such tasks could never be completed | aligned with `TaskType` |
| R15 | `http_request` never returned `json` (called `.json()` on a streamed response) | parse collected bytes; covered by CP-21 tests |
| R16 | `run_python` / `legacy_robot_wrapper` wrote unmasked stdout/stderr to workspace files (A6) | masked before writing; covered by CP-25 tests |
| R17 | Vault token lived in `config.yaml` | `vault_token_env` (DECISIONS 9.6) |
| R18 | Masker masked 1-character secrets, corrupting outputs | min length 4 (DECISIONS 9.5) |
| R19 | A file-arrival trigger rejected by the duplicate guard marked the file processed forever | marker removed on rejection |
| R20 | Migration `7ffcb5d8ab0e` added NOT NULL columns without server defaults (upgrade of a non-empty DB fails) | server defaults added |
| R21 | pre-commit ruff hook pinned to v0.8.6 disagreed with the locked ruff | hooks run `uv run ruff` (DECISIONS 9.7) |

Deferred to the activity checkpoints (tracked there, not yet fixed): CSV read is not streamed (CP-23 memory gate); ZIP size cap trusts declared sizes and has no entry-count cap (CP-23); `oracle_bulk_load` has no MERGE (CP-20); `matching` lacks amount/date tolerance and 1:N and is O(n*m) (CP-26); `legacy_robot_wrapper` lacks exit-code mapping and output-file collection (CP-25).

## Implementation snapshot (code present, not a completion claim)

- Python 3.12 + FastAPI control plane, SQLAlchemy/Alembic, DB-backed bus, worker process isolation and run engine.
- Auth/session/CSRF/RBAC, audit hash chain with append-only ORM guard, secret store, workflow schema/validator/versioning/promotions, API routes, WebSocket events, CLI.
- Activity library: echo/fail/sleep, SQL/Oracle, CSV/Excel/ZIP/text, HTTP/download/SFTP/UNC/email/Graph, Playwright, legacy wrapper/run_python, matching/human_task/ai_extract.
- Local fakes: HTTP/portal/Graph/LLM app, SMTP sink, SQLite GL seed.
- Tests: config/logging/audit, auth/RBAC/CSRF, workflow contracts, engine routing/retries/foreach/sub-workflow/human-task/duplicate guard.
- **Not started:** `web/` frontend and `web/dist` bundle.

## Checkpoint status

Status values: `todo`, `in-progress`, `done`, `blocked`, `skipped-gap`. `in-progress*` means code exists ahead of the checkpoint gate but the checkpoint has **not** been formally verified or tagged.

| ID | Title | Status | Commit | Verified by (command -> result) |
|---|---|---|---|---|
| CP-00 | Bootstrap: git, tracker, baseline commit | done | `fdeef4e` | `git log` -> baseline commit; `git status` -> clean at CP-00 |
| CP-01 | Repository skeleton and Python tooling | done | `96bd415` | `uv sync` ok; `ruff check .` pass; `ruff format --check .` pass; `mypy --strict app activities fixtures` pass (80 files); `pytest` 51 passed; `lint-imports` 1 kept; `pre-commit run --all-files` all passed |
| CP-02 | Configuration, settings and injected clock | done | (cp-02 tag) | `pytest tests/unit/test_settings_clock_logging.py` 15 passed: safe defaults with no file, repo config.yaml holds no secret keys, file < env < init layering, 6 invalid-value rejections, Fake/System clock, container wiring |
| CP-03 | Structured logging, correlation id, secret masking | done | (cp-03 tag) | planted secret never in log file (`test_logs_are_masked...`); every line incl. stdlib loggers carries a correlation id; run/step ids bound in engine + worker (`correlation_scope`); generated run correlation ids; OTel `app/telemetry.py` off by default, no-op without extra (tests pass) |
| CP-04 | Database layer and first Alembic migration | done | (cp-04 tag) | `tests/integration/test_database.py` 3 passed: `alembic upgrade head` == models (compare_metadata empty), dashboard indexes present, audit lock row seeded, `downgrade base` leaves no tables; UTC round trip; `scripts/gen_data_model.py --check` (docs/DATA_MODEL.md, 25 tables + Oracle dialect notes) |
| CP-05 | Immutable hash-chained audit | done | (cp-05 tag) | `tests/integration/test_audit.py` 9 passed: chain verifies after 250 writes; 4 raw-SQL tamper/delete cases detected; static scan of app/activities/fixtures/scripts finds no UPDATE/DELETE path; ORM guard rejects object update, delete and bulk update; `verify-audit` CLI exit 0/1; API search filters + verify + RBAC; concurrent-writer chain test (review R5) |
| CP-06 | Secret store interface and adapters | done | (cp-06 tag) | `tests/integration/test_secrets.py` 6 passed: local resolve/missing/metadata/rotation; env only via `UAF_SECRET_` prefix; Vault adapter with stub client (missing vs outage); reserved platform secrets refused; planted secret absent from run/step/audit records, API run detail + secrets listing, log file and workspace files. Hardening: DECISIONS 9.9 |
| CP-07 | Authentication, sessions and RBAC | done | (cp-07 tag) | `tests/integration/test_auth_rbac.py` 13 passed: 5 roles x 15 endpoints allowed/denied; every mutating /api route (OpenAPI-enumerated) rejects a missing CSRF token (found `/workflows/validate` unguarded, fixed); `serve` exits 2 with no admin; 5 weak/default passwords refused via API; login, user create and role change audited with before/after; single-step run isolated + Admin-only for code (DECISIONS 9.10). Plus `tests/test_auth_api.py` (rate limit, expiry, cookie, CSRF) |
| CP-08 | Workflow definition schema and validator | done | (cp-08 tag) | `tests/unit/test_workflow_validator.py` 8 passed: Hypothesis properties (valid chains round-trip through YAML; back edges -> cycle; unknown activity on exactly that step; missing-step references; disconnected step unreachable; validator never crashes on 150 random routing graphs); `docs/schemas/workflow-v1.json` current (`scripts/gen_schemas.py --check`), Draft 2020-12 valid; `validate` CLI exit 0/1/2 |
| CP-09 | Version registry, environments, promotion and SoD | done | (cp-09 tag) | `tests/integration/test_promotion_api.py` 3 passed (separate client per user): saves create immutable versions + step diff; prod refuses unpromoted (API + engine); dev->prod blocked without exact test approval; requester and version author cannot decide; operator/author lack approve; double decision 409; prod pinned to promoted v1 when v2 exists; all audited. Plus review regressions R12 |
| CP-10 | Job/result envelope contract | done | (cp-10 tag) | `tests/contract/test_activity_contract.py` 59 passed: metadata/schema/sensitive-field/option checks and never-raises over every discovered activity + dummy + template; exception masking; output size cap; sample envelopes validate against `docs/schemas/envelope-v1.json` (found and fixed nested `$defs` that made the published schema unusable); child process answers with schema-valid envelopes keeping `iteration`. `docs/ENVELOPE.md` written |
| CP-11 | Activity framework, registry and discovery | done | (cp-11 tag) | `tests/integration/test_activity_framework.py` 5 passed: drop-in file listed by `list-activities` (broken drop-in tolerated) and runs in a workflow with no engine change; dependent options (`excel.sheet`) via `POST /api/activities/{name}/options/{field}` against a pinned run workspace, traversal refused; `docs/ACTIVITIES.md` current (`scripts/gen_activity_docs.py --check`); template < 30 lines and passes the contract suite. `docs/WRITING_AN_ACTIVITY.md` written; `operation_fields` added for Resource/Operation forms |
| CP-12 | Message bus interface and adapters | done | (cp-12 tag) | `tests/integration/test_bus.py` 9 passed: enqueue/claim/ack/retry/dead-letter/lease redelivery (incl. extended lease)/orphan release/cancel/concurrent claimers/no double processing; `bus.adapter: rabbitmq` refused at startup (DECISIONS 9.12, gap G7) |
| CP-13 | Worker runtime | done | (cp-13 tag) | `tests/integration/test_worker.py` 7 passed: timeout kills the activity and its grandchild, crashed child becomes a failed result, two workers overlap jobs with no double processing, secrets arrive by stdin only and are masked in results/bus/workspace/env, missing secret fails without dispatch, built-ins run under the worker. `.venv` process-tree kill via psutil |
| CP-14 | Run engine | done | (cp-14 tag) | `tests/test_engine.py` 8 passed: multi-step reference/outputs, failure routing + retry attempts, foreach aggregation, pinned sub-workflow, human-task suspend/resume, duplicate guard, bad-reference incident faults the run, persistence `none` keeps inputs/outputs out of run records and step/run audit trail present |
| CP-15 | Durable resume, suspension and crash recovery | in-progress* | | human-task suspend/resume test passes; crash-recovery test todo |
| CP-16 | Triggers, scheduler and duplicate-run guard | in-progress* | | duplicate guard test passes; cron/webhook/file/dependency tests todo |
| CP-17 | Human tasks, SLA and alerting | in-progress* | | task completion/resume test passes; SLA/overdue tests todo |
| CP-18 | REST API completion, live events, health and metrics | in-progress* | | auth/workflow/admin API tests pass; full resource/WebSocket tests todo |
| CP-19 | Local fixtures | in-progress* | | fake HTTP/portal/Graph/LLM, SMTP sink and GL seed exist; SFTP fake and tests todo |
| CP-20 | Activities: GL and Oracle | in-progress* | | code + mypy only; no activity test yet |
| CP-21 | Activities: HTTP, download, SFTP, UNC archive | in-progress* | | code + mypy only; no fixture test yet |
| CP-22 | Activities: email and Graph mail | in-progress* | | code + mypy only; fake endpoint exists but is not exercised |
| CP-23 | Activities: file tools | in-progress* | | code + mypy only; no fixture test yet |
| CP-24 | Activities: Playwright robot and script | in-progress* | | code + mypy only; browser install/runtime not tested |
| CP-25 | Activities: legacy wrapper and run_python | in-progress* | | code + mypy only; no process test yet |
| CP-26 | Activities: matching, human_task, ai_extract | in-progress* | | code + mypy only; human_task engine path tested, activities not |
| CP-27 | Frontend foundation and design language | todo | | not started |
| CP-28 | App shell, navigation and command palette | todo | | not started |
| CP-29 | Operations Console | todo | | not started |
| CP-30 | Task Inbox | todo | | not started |
| CP-31 | Workflow Studio | todo | | not started |
| CP-32 | Admin | todo | | not started |
| CP-33 | Pages, data views and saved views | todo | | not started |
| CP-34 | Acceptance A1: standard pattern end to end | todo | | not started |
| CP-35 | Acceptance A2, A6, A7: HITL, secrets, audit | todo | | not started |
| CP-36 | Acceptance A3, A4, A5: SoD, crash recovery, triggers | todo | | not started |
| CP-37 | Acceptance A8, A9: performance and reuse | todo | | not started |
| CP-38 | End-to-end browser tests | todo | | not started |
| CP-39 | Security hardening and threat model | todo | | not started |
| CP-40 | CI pipeline and quality gates | todo | | not started |
| CP-41 | Documentation set | todo | | not started |
| CP-42 | Final verification (A10) and handover | todo | | not started |

## Work in progress (current checkpoint only)

- [ ] CP-15: crash-recovery and resume-mode tests.

## Blockers and workarounds

| Date | Checkpoint | Blocker | Workaround taken | Logged in KNOWN_GAPS.md? |
|---|---|---|---|---|
| 2026-10-22 | CP-00 | a reference document was absent from the working tree | proceeded without it; recorded the gap | yes (G1, later withdrawn) |
| 2026-10-22 | CP-19/24 | Playwright browser install not attempted; real Oracle/Graph/Vault/RabbitMQ/SFTP unavailable | local fakes where implemented; remaining fakes/tests listed in gaps | yes (G2-G8, G11, G13) |

## Session log (append only, newest last)

| Date/time | Session | Checkpoints touched | Summary | Last commit |
|---|---|---|---|---|
| 2026-10-22 | build-1 | CP-00 | git init, repo-local identity, .gitignore, baseline commit. A reference document was absent; gap recorded (G1, later withdrawn). | cp-00 |
| 2026-10-22 | build-2 | CP-01 to CP-26 (code only) | Built backend foundation, API/CLI, activity library, fakes and tests. Fixed bus timestamp claim, audit bulk mutation guard and foreach. `pytest` 26 passed; ruff/format/mypy/lint-imports pass. Paused on request; formal checkpoint verification remains. | wip(cp-01) |
| 2026-10-22 | build-3 | CP-01 (+ CP-04/05/09/12/14/15/16 fixes) | Full code review: 21 defects found and fixed (see "Code review"), incl. a failing test, double execution on recovery, audit chain fork, unenforced admin-only activities. Added 25 regression/bus tests. All gates incl. pre-commit and Alembic round trip pass. CP-01 closed. | cp-01 |
| 2026-10-22 | build-3 | CP-02, CP-03 | Added defaults/override/invalid/clock/DI tests; per-run/step correlation ids in engine and worker, generated run correlation ids; OTel hook module (off by default). 66 tests pass. | cp-03 |
| 2026-10-22 | build-3 | CP-04, CP-05, CP-06, CP-07 | Verified DB/migrations, audit chain + CLI, secret store and auth/RBAC/CSRF gates; added the tests recorded in the table. | cp-07 |
| 2026-10-22 | build-3 | CP-08, CP-09, CP-10, CP-11 | Verified schema/validator, promotion/SoD, envelope contract and activity discovery gates; wrote ENVELOPE/ACTIVITIES/WRITING_AN_ACTIVITY docs. | cp-11 |
| 2026-10-23 | build-4 | CP-12 | Closed the bus checkpoint: 9 integration tests pass; `bus.adapter: rabbitmq` now refused at startup (DECISIONS 9.12) and G7 reworded around an outbox relay. | cp-12 |
| 2026-10-23 | build-4 | CP-13 | Direct worker-runtime tests: grandchild process-tree kill on timeout, crash envelope, two-worker overlap without double processing, stdin-only secrets absent from env/workspace/bus, missing-secret failure. | cp-13 |
| 2026-10-23 | build-4 | CP-14 | Engine gate closed with incident, persistence and audit assertions added to the routing/retry/foreach/sub-workflow suite. | cp-14 |
