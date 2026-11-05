Repository: WorkTree, a Python/FastAPI workflow automation platform with a Vue 3 + strict TypeScript frontend in `web/`. You are in your own git worktree. Work only in `web/`.

GOAL
Build the Operations Console (CP-29 in `docs/BUILD_CHECKPOINTS.md`). This is the screen people watch while automations run, so it must feel fast, dense and trustworthy. Temporal Web UI and GitHub Actions are the references. You own the detailed UI decisions within the structure below.

READ FIRST
`docs/design-language.md` (binding), `docs/UI_reference_list.md`, `web/src/views/DesignView.vue` (every shared component and state), `web/src/components/shell/AppPage.vue`, `web/src/router/areas/operations.ts` and `web/src/router/types.ts`, `web/src/components/RunTimeline.vue`, `web/src/api/live.ts`, `web/src/api/client.ts`, and `docs/openapi.json` for `/api/dashboard`, `/api/runs`, `/api/runs/{run_id}`, `/api/runs/{run_id}/retry`, `/api/runs/{run_id}/cancel`, `/api/workflows`, `/api/workflows/{workflow_id}/run`, `/api/workflows/{workflow_id}/runnable`, `/api/schedules` and `/api/artifacts/{artifact_id}/download`. Permissions are in `app/security/rbac.py`.

FIRST, CLOSE THESE GAPS IN SHARED COMPONENTS
1. `USelect` and `UTextArea` gain `description` and `error`, using the same `field.ts` and `FieldMessages.vue` approach as `UTextInput`.
2. Fix the small label offset so `USelect` and `UTextInput` line up in a row.
3. `UDialog` gains `persistent?: boolean`: when true, a backdrop click does not close it, for dialogs holding a form. Escape and the close button still work.
4. `UTabs`' selected underline uses `--uaf-accent-text`, because `--uaf-accent` is about 2.7:1 on dark.

SCREENS
Add these routes in `web/src/router/areas/operations.ts`, with views in `web/src/views/operations/`, and show Dashboard, Runs and Schedules as children of Operations in the sidebar.

1. Dashboard, `/operations`. Plain numbers, no tiles or cards with icons: running, waiting (suspended), failed, open tasks, overdue tasks. Each number links to the filtered view behind it. Below it, a compact "Needs attention" list of failed runs and a recent runs table. Overdue tasks link to `/inbox`. Include a "Run now" primary action for users allowed to trigger runs.

2. Run history, `/operations/runs`. `DataTable` with status, workflow, environment, trigger, requested by, started, duration. `FilterBar` with search, status, environment, trigger and a time range (24 hours, 7 days, 30 days, all). Server-side sort and pagination through `/api/runs`. Filters, sort and page live in the URL query so a view can be shared and survives reload. Rows open the detail page.

3. Run detail, `/operations/runs/:runId`. GitHub Actions style. Page title is the workflow name with a `StatusBadge`. The main column is the collapsible step list using `RunTimeline`: outcome, duration, attempts, retry and incident information, and an expandable masked log in `CodeBlock`. The first failed step opens automatically. A properties column on the right uses `PropertyList`: workflow, version, environment, trigger, requested by, started, finished, duration, correlation id, parent run link. Tabs for Steps, Artifacts (with download links) and Incidents, with counts. Actions: "Retry from failed step" when the run failed, and "Cancel" through `ConfirmDialog` when it is active. Replay on the canvas belongs to the Studio and is out of scope.
   Secrets are masked by the API. Never un-mask or reconstruct anything.

4. Schedules, `/operations/schedules`. `DataTable` of schedules with workflow, kind, cron and timezone, next run and last run. An enable or disable `USwitch` is shown only to users allowed to change schedules, with a toast and rollback when the request fails.

5. Run now dialog, reusable from the dashboard and the palette. `UDialog` with `persistent`. Choose a workflow, using `/runnable` to explain why one cannot run. Choose the environment and enter inputs as JSON in a `UTextArea` with inline validation; offer named fields only if the API gives you the input schema. Send one `Idempotency-Key` per dialog open, so a double click cannot start two runs. On success, go to the run. Duplicate-guard feedback is a designed moment:
   - HTTP 409 `duplicate_run`: stay in the dialog with a `MessageBar` that names the active run and links to it.
   - HTTP 200 with `trigger_detail.queued`: go to the run, which shows that it is queued behind the linked active run.
   The full contract is the docstring of `start_run` in `app/api/runs.py`.

LIVE UPDATES
Use `useLiveEvents`. There are no run-started or step-started events: on `step.completed` or `run.finished`, invalidate the affected queries. While a run on screen is `pending`, `running` or `suspended`, also poll every 3 s, and poll whenever the socket is disconnected, so the view is never more than 5 s stale. Show a quiet "Live updates paused" `MessageBar` only after the socket has been down for more than 10 s. Do not refetch on `ping`.

BEHAVIOUR THROUGHOUT
- Use vue-query with stable query keys, shared components and `LoadState` for loading, error and empty states.
- Show what the user can do: hide actions they lack permission for using the session store, and still handle a 403 politely. The API enforces every rule.
- Empty states are a title and one sentence with the next step.
- Every screen works by keyboard. Add palette commands: Go to runs, Go to schedules, Run now. Use the `commands` export.
- Compact by default, must not break at 1024 px, and must look right in all three themes and both densities.
- All visible text is plain sentence case.

TESTS
`web/tests/operations.test.ts`, with `fetch` and the WebSocket faked: filters written to and read from the URL, sort and pagination, live event invalidation, polling while active and stopping when finished, the 409 and queued outcomes, idempotency key stable within one dialog, retry and cancel, permission-based hiding, and the schedule toggle rollback. Add tests for the four shared component gaps.

MANUAL CHECK REQUIRED BY CP-29
Run the real backend against a scratch data folder and verify in a headless browser that a run started from the UI shows step updates in the run detail within 5 s. Do not touch `runtime/`: set `UAF_DATABASE__URL` and the data folder to a temp path through environment variables. `uv run uaf --help` lists the commands. Report what you did and saw, including whether the logged-out socket behaves; a known backend issue makes the auth close reach the browser as 1006, and that is being fixed separately.

CONSTRAINTS
- Touch only `web/src/views/operations/`, `web/src/router/areas/operations.ts`, `web/src/components/` (the four gaps, plus new Operations components if truly shared), `web/src/views/DesignView.vue` if a shared component changes, and `web/tests/`.
- Do not change the backend. If an endpoint is missing or wrong, work around it only if that is clean, and list it in your summary.
- `docs/design-language.md` is binding. If you think a locked decision is wrong, leave it and raise it.
- Do not weaken existing tests. No new dependencies. Do not run `vite build` or change `web/dist`; it is built at merge time. For browser checks use the Vite dev server.
- Put helper scripts in files rather than quote-heavy heredocs, and delete scratch files before finishing. If `node_modules` is missing, run `npm ci` in `web/`.
- Do the work yourself: start no subagents.

DONE WHEN (run in `web/` and report each)
- `npx vue-tsc --noEmit`, `npx eslint .`, `npx vitest run`, `npm run icons:check`, `npm run api:check` pass
- the manual check is done

Commit on this worktree's branch with subject `feat(web): add the Operations console`, a body wrapped at 72 characters explaining why, and the footer `Refs: CP-29`. Do not mention any AI or tool in the message, and add no Co-Authored-By trailer. Never use `--no-verify`. Do not push.

When finished, reply with what you built, the results of each check including the manual one, any backend gaps, any design decision you think should be revisited, your worktree path and branch, and the commit hash.
