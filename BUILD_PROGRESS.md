# BUILD_PROGRESS: UAF Python/FastAPI MVP

The resume point for the build agent. **Read this file first on every start or restart.** Checkpoint definitions are in `docs/BUILD_CHECKPOINTS.md`. Process rules are in `docs/AGENT_START_PROMPT.md`.

## Current position
- **Current checkpoint:** CP-01
- **Status:** in-progress
- **Next action:** CP-00 committed. Build the project skeleton, `pyproject.toml`, tooling config and layering check.
- **Last commit:** cp-00 baseline
- **Last updated:** 2026-10-22

## Checkpoint status
Status values: `todo`, `in-progress`, `done`, `blocked` (with a reason and the workaround taken), `skipped-gap` (logged in `KNOWN_GAPS.md`).

| ID | Title | Status | Commit | Verified by (command → result) |
|---|---|---|---|---|
| CP-00 | Bootstrap: git, tracker, baseline commit | done | (see git log) | `git log` → baseline commit; `git status` → clean |
| CP-01 | Repository skeleton and Python tooling | todo | | |
| CP-02 | Configuration, settings and injected clock | todo | | |
| CP-03 | Structured logging, correlation id, secret masking | todo | | |
| CP-04 | Database layer and first Alembic migration | todo | | |
| CP-05 | Immutable hash-chained audit | todo | | |
| CP-06 | Secret store interface and adapters | todo | | |
| CP-07 | Authentication, sessions and RBAC | todo | | |
| CP-08 | Workflow definition schema and validator | todo | | |
| CP-09 | Version registry, environments, promotion and SoD | todo | | |
| CP-10 | Job/result envelope contract | todo | | |
| CP-11 | Activity framework, registry and discovery | todo | | |
| CP-12 | Message bus interface and adapters | todo | | |
| CP-13 | Worker runtime | todo | | |
| CP-14 | Run engine | todo | | |
| CP-15 | Durable resume, suspension and crash recovery | todo | | |
| CP-16 | Triggers, scheduler and duplicate-run guard | todo | | |
| CP-17 | Human tasks, SLA and alerting | todo | | |
| CP-18 | REST API completion, live events, health and metrics | todo | | |
| CP-19 | Local fixtures | todo | | |
| CP-20 | Activities: GL and Oracle | todo | | |
| CP-21 | Activities: HTTP, download, SFTP, UNC archive | todo | | |
| CP-22 | Activities: email and Graph mail | todo | | |
| CP-23 | Activities: file tools | todo | | |
| CP-24 | Activities: Playwright robot and script | todo | | |
| CP-25 | Activities: legacy wrapper and run_python | todo | | |
| CP-26 | Activities: matching, human_task, ai_extract | todo | | |
| CP-27 | Frontend foundation and design language | todo | | |
| CP-28 | App shell, navigation and command palette | todo | | |
| CP-29 | Operations Console | todo | | |
| CP-30 | Task Inbox | todo | | |
| CP-31 | Workflow Studio | todo | | |
| CP-32 | Admin | todo | | |
| CP-33 | Pages, data views and saved views | todo | | |
| CP-34 | Acceptance A1: standard pattern end to end | todo | | |
| CP-35 | Acceptance A2, A6, A7: HITL, secrets, audit | todo | | |
| CP-36 | Acceptance A3, A4, A5: SoD, crash recovery, triggers | todo | | |
| CP-37 | Acceptance A8, A9: performance and reuse | todo | | |
| CP-38 | End-to-end browser tests | todo | | |
| CP-39 | Security hardening and threat model | todo | | |
| CP-40 | CI pipeline and quality gates | todo | | |
| CP-41 | Documentation set | todo | | |
| CP-42 | Final verification (A10) and handover | todo | | |

## Work in progress (current checkpoint only)
The sub-steps of the current checkpoint: done ones ticked, the next one stated. Clear this section when the checkpoint is done.

- [ ] (none yet)

## Blockers and workarounds
| Date | Checkpoint | Blocker | Workaround taken | Logged in KNOWN_GAPS.md? |
|---|---|---|---|---|

## Session log (append only, newest last)
| Date/time | Session | Checkpoints touched | Summary | Last commit |
|---|---|---|---|---|
| 2026-10-22 | build-1 | CP-00 | git init, repo-local identity, .gitignore, baseline commit. Note: a reference document is absent from the working tree; recorded as a gap. | cp-00 |
