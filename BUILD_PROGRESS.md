# BUILD_PROGRESS: UAF Python/FastAPI MVP

The resume point for the build agent. **Read this file first on every start or restart.** Checkpoint definitions are in `docs/BUILD_CHECKPOINTS.md`. Process rules are in `docs/AGENT_START_PROMPT.md`.

## Current position
- **Current checkpoint:** CP-28 (next)
- **Status:** backend and activity checkpoints CP-01 to CP-26 are closed. The `pdf`, `document` and `spreadsheet` activities, and `excel` recalculation, now run on pypdf, plain docx XML (lxml) and a Python port of the GridCraft formula engine (`activities/_formula`); no CraftApps binary or LibreOffice is used (DECISIONS 11.12-11.14; G9, G16). CP-27 (frontend foundation and design language) is closed; CP-28 onward has not started.
- **Next action:** CP-28: app shell (collapsible left sidebar, breadcrumbs, Ctrl/Cmd+K palette), login page, message bars and toasts, keyboard access. Read `docs/design-language.md` first.
- **Owner feedback (2026-10-23): the node cards still need design.** The flat `NodeCard` in `web/src/components/NodeCard.vue` is a stand-in; the owner is not satisfied with it. Do not treat it as final. Agree the node card design with the owner (show options) before building the Studio canvas in CP-31.
- **Last commit:** see `git log -1`.
- **Last updated:** 2026-10-23

## Verification snapshot (run, not assumed)

| Gate | Command | Result |
|---|---|---|
| Tests | `uv run pytest -q` | **763 passed**, 0 failed, 0 skipped (build-8 full run with the web bundle present, ~25 min); `npm --prefix web test`: **80 passed** |
| Lint | `uv run ruff check .` | passed |
| Format | `uv run ruff format --check .` | passed (186 files) |
| Types | `uv run mypy --strict app activities fixtures` | passed (98 source files) |
| Layering | `uv run lint-imports` | passed (1 contract kept) |
| Hooks | `uv run pre-commit run --all-files` | all hooks passed |
| Migrations | `alembic upgrade head` / `downgrade base` / `upgrade head` / `alembic check` (scratch SQLite) | passed; "No new upgrade operations detected" |

**Not yet verified:** coverage percentage; the whole frontend; acceptance items A1-A10; Firefox/WebKit robots; the formula engine against real Excel.

## Code review (2026-10-23, build-7): platform and CP-24 draft

Second full review: engine, auth, API boundary, worker launcher, and the paused CP-24 browser code. Each item is fixed with a regression test in `tests/integration/test_platform_review.py` (engine/auth/webhook/env) or `tests/integration/test_browser_activities.py` (R44-R46).

| # | Defect | Fix |
|---|---|---|
| R34 | **Correctness:** `duplicate_guard: queue` never queued: the duplicate was flagged but advanced at once, running in parallel with the run it should wait for | not advanced until the run ahead finishes (DECISIONS 11.3) |
| R35 | Two queued runs with the same `created_at` each saw the other as earlier and waited forever | strict (`created_at`, `id`) order |
| R36 | `recover()` turned queued (pending) duplicates into running | queued runs stay pending |
| R37 | The tick advanced all runs in one session: a run failing half-way still committed its partial changes | one transaction per run, incident in a fresh one (DECISIONS 11.1) |
| R38 | Human-task completion bypassed the engine lock (R6), racing the tick; taking it late could deadlock against SQLite | lock taken before the first write (DECISIONS 11.2) |
| R39 | `human_task` inputs were not validated: an unknown type/role created a task nobody could complete; a bad `due_minutes` crashed the tick | validated by the activity model, `bad_inputs` incident (DECISIONS 11.4) |
| R40 | **Security:** activity child processes inherited the server environment, including `UAF_SECRET_*` (e.g. the session signing key) and the Vault token | stripped; child settings via `UAF_CHILD_*` (DECISIONS 11.5) |
| R41 | **Security:** the unauthenticated webhook returned the full run record (inputs, workspace path, correlation id) and accepted unbounded bodies | id/status/trigger only, 1 MiB cap, object-only (DECISIONS 11.6) |
| R42 | The last Admin could demote or deactivate themselves (no one left to administer); role change for an unknown user was a 500 | 409 guard, 404 (DECISIONS 11.7) |
| R43 | Login timing revealed whether a username exists (no argon2 work for unknown users) | equal-cost dummy verification |
| R44 | CP-24 draft: the portal lock wrapped the whole robot (robots on one portal serialised end to end) and was broken as "stale" after 5 min while a live login waited up to 900 s for an OTP | lock only the session phase; abandoned only when the owner pid is gone (DECISIONS 11.8) |
| R45 | CP-24 draft: login failure detected by fixed words anywhere on the page ("Invalid invoices: 3" = failed login) and read before the post-submit page loaded | configurable markers + selector; wait for load after submit |
| R46 | CP-24 draft: Playwright state folder setting was ignored in workers (fell back to the OS temp dir); a `file:` URL got a misleading "base_url required" error | `UAF_CHILD_PLAYWRIGHT_STATE`; any URL with a scheme goes to `validate_url` |

## Code review (2026-10-23, build-5): activity library

Review of `activities/` (CP-20 to CP-26 code, previously "code + mypy only"). Each item is fixed and has a regression test in `tests/integration/test_activity_review.py` (10 of its 11 tests fail on the pre-fix code; the 11th pins the happy-path move). This did **not** close CP-20 to CP-26 by itself; their own gates were still open (CP-20 is now closed).

| # | Defect | Fix |
|---|---|---|
| R22 | **Security (A6):** `run_python` / `legacy_robot_wrapper` wrote the command line unmasked into the workspace log, so a secret passed in `args` leaked (R16 masked only stdout/stderr) | whole log text masked (`_write_log`) |
| R23 | `run_python` decoded child output with the Windows ANSI code page while forcing the child to UTF-8: non-ASCII output raised or was garbled | decode UTF-8, `errors="replace"`; legacy wrapper also `errors="replace"` |
| R24 | `run_python` timeout surfaced as a raw `TimeoutExpired` with the full command line | clean "script exceeded Ns" failure |
| R25 | `matching` collapsed right rows with duplicate keys into one entry: rows vanished from both matched and unmatched outputs | 1:1 pairing with per-key row lists, exact-key fast path (DECISIONS 10.1) |
| R26 | `unc_archive` move deleted the source before the checksum check; a mismatch lost the only good copy and left the bad one | copy, verify (expected or source hash), delete; bad copy removed (DECISIONS 10.2) |
| R27 | `download_file` checksum compare was case-sensitive and a mismatch left the bad file in the workspace | normalised compare; file removed on mismatch |
| R28 | `csv` append wrote rows in the new rows' key order, not the existing header's (silent column shift) | follows the existing header |
| R29 | CSV reads (`csv` read, `read_table` used by bulk load/matching) produced `NaN` for empty cells: invalid JSON output and float NaN loaded into DB columns | empty cells become `None` (`csv_records`) |
| R30 | `excel set_cells` on an unknown sheet silently wrote into the active sheet | fails with "sheet not found" |
| R31 | `sftp list` returned the raw `st_mode` int as `directory`; private keys were RSA-only | boolean `S_ISDIR`; `PKey.from_path` (any key type) |
| R32 | Graph `mailbox`/`sender` interpolated unescaped into the URL path | `quote(..., safe="@")` |
| R33 | Fake SFTP fixture thread crashed (`EOFError`) when a client hung up mid-handshake, an unhandled-thread warning in the suite | `EOFError` handled like other disconnects |

Found but **not** fixed (policy calls or later checkpoints): `unc_archive.destination_dir` and `sql`/`oracle_*` `db_url` accept any location/URL the author writes (no allow-list; CP-39 threat model); `email` SMTP has no STARTTLS, so `smtp_password` goes over plaintext (CP-22). The deferred list below still applies.

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

Deferred to the activity checkpoints (tracked there, not yet fixed): `matching` lacks amount/date tolerance and 1:N and is O(n*m) (CP-26); `legacy_robot_wrapper` lacks exit-code mapping and output-file collection (CP-25).

## Implementation snapshot (code present, not a completion claim)

- Python 3.12 + FastAPI control plane, SQLAlchemy/Alembic, DB-backed bus, worker process isolation and run engine.
- Auth/session/CSRF/RBAC, audit hash chain with append-only ORM guard, secret store, workflow schema/validator/versioning/promotions, API routes, WebSocket events, CLI.
- Activity library: echo/fail/sleep, SQL/Oracle, CSV/Excel/ZIP/text, HTTP/download/SFTP/UNC/email/Graph, Playwright, legacy wrapper/run_python, matching/human_task/ai_extract.
- Local fakes: HTTP/portal/Graph/LLM app, root-confined SFTP server, SMTP sink, SQLite GL seed and ignored data generators (AES-256 ZIP/Excel/fixed-width/log).
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
| CP-15 | Durable resume, suspension and crash recovery | done | (cp-15 tag) | `tests/integration/test_recovery.py` 5 passed: a real child service process crashes mid-run and the restarted container resumes from the last completed step; `resume: restart` re-runs the in-flight step (marker written twice) while `resume: skip` marks it done (written once) and advances; a suspended human-task resume token survives a restart; `retry_from_failed_step` reopens the failed step and writes `run.retry` audit |
| CP-16 | Triggers, scheduler and duplicate-run guard | done | (cp-16 tag) | `tests/integration/test_triggers.py` 10 passed: strict-after cron + single fire per slot, missed slot skipped and audited, catch-up drains one missed slot per tick, webhook token fires/merges payload and disable/unknown token 404, file arrival once per path+sha256 and again on new content, duplicate-guard rejection deletes the processed marker and retries after the active run, dependency trigger passes upstream run/output and fires once, `Idempotency-Key` replays the run / 409 on a different body, invalid cron and manual schedules refused |
| CP-17 | Human tasks, SLA and alerting | done | (cp-17 tag) | `tests/integration/test_tasks.py` 9 passed: all four task types claim (role-gated, 409 on double claim), validate decisions (reject needs a reason) and resume the run; manual-match pairs stored; reject routes through `on_failed`; task SLA breach notifies the assignee role once, is audited and drives the overdue view/RBAC; active-run workflow SLA breach; webhook + SMTP delivery with masking; a broken channel never loses the notification |
| CP-18 | REST API completion, live events, health and metrics | done | (cp-18 tag) | `tests/integration/test_api.py` 9 passed: every BP:42 resource (workflows/versions/environments/runs/tasks/schedules/users+roles/audit/secrets metadata/artifacts) plus dashboard, activities, views, notifications; error envelope 404/422 and no traceback (fixed pydantic `ValidationError` -> 422 in save/validate); WebSocket delivers `step.completed`+`run.finished` to a test client and rejects anonymous subscribers; `/health`, Prometheus `/metrics`; `scripts/export_openapi.py --check` keeps the 48-path `docs/openapi.json` current |
| CP-19 | Local fixtures | done | (cp-19 tag) | `tests/integration/test_fixtures.py` 7 passed from pytest fixtures: fake portal (form login, email OTP, session cookie file download, API-token mode), fake Graph (token, `$filter`/`$orderby`/`$top`/`$select`, sendMail, drive upload), fake LLM completion, paramiko SFTP (put/get/list/mkdir/rename, root confinement, clean stop), SMTP sink delivery, deterministic SQLite GL, and data generators (1M-row CSV in an AES-256 ZIP, 500-row Excel, fixed-width and log samples); generated files are git-ignored. Real hosts remain gaps G3/G4/G5/G11 |
| CP-20 | Activities: GL and Oracle | done | (cp-20 tag) | `tests/integration/test_sql_activities.py` 10 passed: aggregate join to Parquet, named binds + `max_rows`, positional placeholders refused, UPDATE and batched executemany with `chunk_size`, multi-statement script, 2,000-row fixture invoices staged then MERGE-upserted without duplicates, per-row errors reported with row indexes, direct load, identifier/URL refusal; contract suite passes; G2 narrowed to real Oracle |
| CP-21 | Activities: HTTP, download, SFTP, UNC archive | done | (cp-21 tag) | `tests/integration/test_network_activities.py` 10 passed: JSON POST + body file, custom/rejected status, response cap, unsafe URLs refused; streamed download with uppercase SHA-256, artifact, mismatch/size-cap cleaning up and HTTP 404; SFTP put/get/list against the paramiko fixture, bad credentials and missing local path; UNC copy/move with checksum, mismatch -> failed with source intact and no destination, overwrite guard |
| CP-22 | Activities: email and Graph mail | done | (cp-22 tag) | `tests/integration/test_mail_activities.py` 8 passed: SMTP body/HTML/attachment delivered to the sink, credentials refused without STARTTLS, connection failure; Graph sendMail with client-secret token and base64 attachment, bad token/endpoint; `graph_read_mail` newest OTP with server-side sender+timestamp filters and the small `$select`, old sender, no-code, bad timestamp/token. G3/G11 updated; DECISIONS 10.3 |
| CP-23 | Activities: file tools | done | (cp-23 tag) | `tests/integration/test_file_activities.py` 16 passed: CSV read streams all three output formats (7/3/50-row chunks), declared encoding/delimiter, `read_fwf(dtype=str)` on 500 fixture rows, write/append/source_path, empty file; Excel sheets/read 500 fixture rows/write with bold header/set_cells/recalculate G9; ZIP AES create/list/extract, zip-slip and size/entry bombs rejected with no partial files, 500-row workbook round trip; text log write/append/tail + 500 fixture log lines; 1M-row CSV measured at **55.8 MB traced peak** (< 500 MB). DECISIONS 10.4 |
| CP-24 | Activities: Playwright robot and script | done | (cp-24 tag) | `tests/integration/test_browser_activities.py` 14 passed against the fake portal + fake Graph (headless Chromium): API-token login sends the header and a wrong token fails; form login downloads the report and saves state (lock released); wrong password; saved session reused, then expired by the portal and renewed; form+OTP reads the fresh code from Graph; OTP mail older than T0 never used; rejected OTP retried with the next fresh code; all OTPs rejected fails after `otp_attempts`; portal lock exclusive and recovers from a dead owner; `playwright_script` result + screenshot, script error -> failed; unsafe URL refused. Review fixes R44-R46. G8 narrowed |
| CP-25 | Activities: legacy wrapper and run_python | done | (cp-25 tag) | `tests/integration/test_process_activities.py` 10 passed: sample legacy robot collects named output files as artifacts; secrets masked in args/env/stdout/stderr/log; exit codes map to outcomes with messages (`success_codes`); missing outputs fail unless optional; output globs confined to the workspace; `UAF_*`/malformed env names refused; timeout kills the robot and its grandchild; `run_python` timeout keeps partial output and JSON result file returned; legacy robot runs under the worker envelope with `{{ secret:... }}` substitution and masking. `run_python` documented as process isolation, not a sandbox (DECISIONS 11.9) |
| CP-26 | Activities: matching, human_task, ai_extract | done | (cp-26 tag) | `tests/integration/test_matching_ai_tasks.py` 15 passed: Hypothesis (300 examples each) - every row accounted for exactly once, no right row reused, pairs respect key/score/amount/date rules, 1:N groups sum within tolerance, deterministic, self-match complete; bank vs ledger 1:1 and 1:N to three Parquet tables; fuzzy only above threshold; human_task suspends and resumes for all four task types; ai_extract refused when disabled, sends the JSON schema to the fake LLM and validates the answer, schema mismatch and invalid schema fail (DECISIONS 11.10, 11.11) |
| CP-27 | Frontend foundation and design language | done | | `web/` (Vite, Vue 3 + TS strict, Router, Pinia, vue-query, Fluent wrappers): tokens and 3 themes with AA contrast tests, own icon set with the leaf/branch mark, StatusBadge, PageHeader, PropertyList, EmptyState, RunTimeline, NodeCard, typed API client generated from `docs/openapi.json` with a freshness check, `docs/design-language.md`; `vue-tsc`, ESLint and 80 Vitest tests pass; bundle built into `web/dist` and served by FastAPI (4 tests) (DECISIONS 11.15, 11.16) |
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

- None: CP-26 closed. CP-27 has not started.

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
| 2026-10-23 | build-4 | CP-15 | Crash-recovery suite: real killed child process, restart/skip modes, suspended token survives restart, audited retry. Fixed `run_activity_process` to stringify a Path extra folder before putting it in the child env. | cp-15 |
| 2026-10-23 | build-4 | CP-16 | Trigger gate: cron/misfire/catch-up, webhook token lifecycle, file arrival/hash dedupe + guard retry, dependency outcome, idempotency-key replay. | cp-16 |
| 2026-10-23 | build-4 | CP-17 | Human-task gate: four task types, claim/complete and resume, rejection reason + on_failed, task and workflow SLA breach (idempotent, audited, role-visible), webhook/SMTP delivery with masking and non-fatal channel failure. | cp-17 |
| 2026-10-23 | build-4 | CP-18 | API gate: resource coverage (added `/api/environments` + `/api/admin/roles`, pagination on workflows/tasks), consistent 404/422 envelope (pydantic validation now 422, not 500), WebSocket run events, health/metrics, OpenAPI exporter + checked-in schema. | cp-18 |
| 2026-10-23 | build-4 | CP-19 | Fixture gate: pytest-owned fake portal/Graph/LLM/SFTP/SMTP/GL, data generators (1M-row AES-256 ZIP, Excel, fixed-width, log), start/stop smoke tests. G5 updated. | cp-19 |
| 2026-10-23 | build-5 | review (CP-20 to CP-26 code) | Re-verified every gate from scratch (all matched the tracker). Reviewed `activities/`: 12 defects fixed (R22-R33), incl. secret leak via logged command line, data loss in `unc_archive` move and `matching`, CSV column shift/NaN. 11 regression tests; 234 pass. CP-20 to CP-26 remain open. | uncommitted |
| 2026-10-23 | build-6 | CP-20 | Added the `Database`/SQLite/Oracle interface (`activities/database.py`), converted the SQL activities to it, implemented staged chunked loads + SQLite upsert/Oracle MERGE + append and per-row errors, used `chunk_size` for batched executes and multi-statement/PLSQL scripts, and refused positional binds. 10 SQLite tests incl. 2,000 fixture invoices. G2 narrowed. 244 pass. | cp-20 |
| 2026-10-23 | build-6 | CP-21 | Fixture tests for HTTP (JSON/caps/status/URL refusal), streamed download (checksum, size cap, 404), SFTP put/get/list + bad credentials against the paramiko fake, and UNC copy/move incl. checksum mismatch -> failed with no data loss and the overwrite guard. G5 updated. 254 pass. | cp-21 |
| 2026-10-23 | build-6 | CP-22 | SMTP fallback (body/HTML/attachment, STARTTLS required for credentials, connection failure) against the sink; Graph sendMail via client-secret token with attachments; `graph_read_mail` filtered server-side by timestamp and sender, `$select` keeps the page small, OTP regex, failure paths. G3/G11 updated; DECISIONS 10.3. 262 pass. | cp-22 |
| 2026-10-23 | build-6 | CP-23 | Streamed CSV/FWF reads (chunked to Parquet/CSV/JSON), declared encodings, Excel read/write/set_cells with XlsxWriter constant memory and opt-in LibreOffice recalculation, AES ZIP create/list/extract with zip-slip plus declared/actual size and entry caps, bounded text-log tail. 16 tests incl. 1M rows at 55.8 MB traced peak. G9/DECISIONS 10.4. 278 pass. | cp-23 |
| 2026-10-23 | build-6 | CP-24 (paused) | Wrote the three login styles, per-portal locked session state/reuse, Graph OTP polling with T0/regex/fresh-code retry, and fake-portal OTP login support. Imports, ruff and mypy pass; no CP-24 tests or gates yet. Paused on request; resume at the browser test suite. | wip(cp-24) |
| 2026-10-23 | build-7 | review, CP-24, CP-25, CP-26, pdf | Second full review: 13 defects fixed (R34-R46) incl. duplicate-guard queue never queuing, per-run tick transactions, lock order, platform credentials leaking into activity children, webhook disclosure, last-admin lockout. Closed CP-24 (browser tests, lock/markers/state fixes), CP-25 (env, exit-code mapping, output files, tree kill), CP-26 (new reconciliation matcher with Hypothesis properties, schema-validated ai_extract). Added the `pdf` activity on PdfCraft (MCP over stdio) and the `document` activity on WordCraft (convert/text/info/mail merge), both from CraftApps, built from source; 8 + 6 engine tests pass. | cp-26 |
| 2026-10-23 | build-8 | engine port (pdf, document, spreadsheet) | Replaced the CraftApps CLI nodes with pure Python: `activities/_formula` (GridCraft port: parser, evaluator, ~140 functions, workbook load/recalculate, XML write-back that keeps charts), `spreadsheet` and `excel` recalculation on it, `pdf` on pypdf, `document` on docx XML with WordCraft-style mail merge. Removed `activities/_engines.py`, the `*_cli` settings and the child env plumbing. 759 passed; all gates green. Redaction, OCR, docx to PDF and some inputs dropped (G16). | uncommitted |
