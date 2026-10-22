# BUILD_PROGRESS: UAF Python/FastAPI MVP

The resume point for the build agent. **Read this file first on every start or restart.** Checkpoint definitions are in `docs/BUILD_CHECKPOINTS.md`. Process rules are in `docs/AGENT_START_PROMPT.md`.

## Current position
- **Current checkpoint:** CP-01
- **Status:** in-progress (paused on request; backend implementation is ahead of the checkpoint gates)
- **Next action:** run the formal CP-01 gate (`pre-commit run --all-files`), commit/tag CP-01, then verify the code that already exists checkpoint by checkpoint (CP-02 to CP-26) instead of assuming it is done.
- **Last commit:** `4dd33b9` (`wip(cp-01): backend foundation, activities, fixtures and tests`).
- **Last updated:** 2026-10-22

## Verification snapshot (run, not assumed)

| Gate | Command | Result |
|---|---|---|
| Tests | `uv run pytest -q --no-header` | **26 passed** |
| Lint | `uv run ruff check .` | passed |
| Format | `uv run ruff format --check .` | passed (120 files) |
| Types | `uv run mypy --strict app activities` | passed (76 source files) |
| Layering | `uv run lint-imports` | passed (1 contract kept) |

**Not yet verified:** CP-01's `pre-commit` gate; Alembic upgrade/downgrade in this session; coverage percentage; worker/bus retry tests; triggers/schedules; activity-library fixture tests; Playwright; the whole frontend; acceptance items A1-A10.

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
| CP-01 | Repository skeleton and Python tooling | in-progress | | ruff/format/mypy/lint-imports pass; `pre-commit` gate pending |
| CP-02 | Configuration, settings and injected clock | in-progress* | | config precedence/validation tests pass; formal checkpoint gate pending |
| CP-03 | Structured logging, correlation id, secret masking | in-progress* | | masking + correlation-id log test passes; formal checkpoint gate pending |
| CP-04 | Database layer and first Alembic migration | in-progress* | | schema created in tests; upgrade/downgrade not re-run in this session |
| CP-05 | Immutable hash-chained audit | in-progress* | | chain verification, tamper detection and ORM mutation rejection tests pass |
| CP-06 | Secret store interface and adapters | in-progress* | | local/env store wired; Vault test still todo |
| CP-07 | Authentication, sessions and RBAC | in-progress* | | login/logout/CSRF/expiry/rate-limit/role-matrix tests pass |
| CP-08 | Workflow definition schema and validator | in-progress* | | schema/reference/validation tests pass |
| CP-09 | Version registry, environments, promotion and SoD | in-progress* | | code present; promotion/SoD tests still todo |
| CP-10 | Job/result envelope contract | in-progress* | | round-trip test passes |
| CP-11 | Activity framework, registry and discovery | in-progress* | | contract/registry/drop-in discovery tests pass |
| CP-12 | Message bus interface and adapters | in-progress* | | used by engine tests; dedicated retry/redelivery tests todo |
| CP-13 | Worker runtime | in-progress* | | exercised through engine tests; direct timeout/secret tests todo |
| CP-14 | Run engine | in-progress* | | multi-step/branch/retry/foreach/sub-workflow tests pass |
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

- [x] Engine integration defects fixed: SQLite bus claim timestamp precision, append-only audit bulk guard, foreach item injection and `inputs.<item>` resolution.
- [x] Test suite added and green (26 tests).
- [x] Lint, format, strict typing and import-layering gates pass.
- [ ] Run `pre-commit run --all-files` and close CP-01.
- [ ] Then verify CP-02 to CP-26 in order, adding the missing tests listed above.

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
