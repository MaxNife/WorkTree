# Next build tasks

Written 2026-11-05, updated 2026-11-09. Work these in order. Before any UI task, read `docs/design-language.md` and the approved screen designs listed in `docs/research/canvas-design/HANDOFF.md`.

## How to run them

- Keep two subagents running: Sonnet 5.5 high, plus a free OpenCode model (`opencode/` first, then `xkiro/`). Use Sonnet medium only when the free models fail.
- All UI work runs on Opus 5.5 medium.
- Start delegates one at a time. Six at once hit OpenCode's free limit.
- Review every result, rerun the gates, then cherry-pick to `main`. Do not push unless the owner asks.

## Queue

1. **SEC-10, Sonnet high, next.** Implement `docs/adr/0001-secret-usage-policy.md`: `credential_inputs`, `destination_inputs`, `allowed_hosts` and `environments` on secret metadata with a migration and Admin API, checks at save, at dispatch and in the test endpoint, egress filtering in `validate_url`, `secrets.enforce_policy` with the prod startup check, secrets listed on promotions, and a names-only secret list for the Studio dropdown. Run A1 and A6 with the policy enforced. Remove G17 when done.
2. **Mask run fields, backend, Sonnet high.** `/api/runs` returns run-level `inputs` and `outputs` unmasked, and `workspace` as an absolute server path. Mask both, and restrict or drop the path.
3. **Live events after logout, small backend fix.** `/api/events` closes before accepting, so the browser sees 1006 and retries for ever. Accept, then close with 1008.
4. **CP-40 CI, free model.** Brief to be recreated from the checkpoint: `.github/workflows/ci.yml` and `docs/CI.md`.
5. **CP-37 A8 and A9 tests, free model.** `tests/acceptance/test_a8_a9.py`. Keep the real limits and report any miss.
6. **Studio graph logic, free model.** Pure TypeScript in `web/src/studio/`: definition to graph and back unchanged, auto-layout, safe edits, client validation.
7. **CP-30 Task Inbox, Opus medium.**
8. **CP-32 Admin, Opus medium.** Include the secret policy editor.
9. **CP-33 Pages and data views, Opus medium.**
10. **CP-31 Studio canvas, Opus medium.** Builds on task 6 and replaces `NodeCard`.
11. **CP-38 browser tests, then CP-41 docs and CP-42 final verification.**

## Waiting on the owner

- Push the commits on `main`, which is ahead of GitHub.
- Commit or drop `AGENTS.md`.
- Rename the `uaf` identifiers, or keep them.
- Replace the `lagos` timezone in `tests/integration/test_database.py`.
- Delete `worktree-original.bundle`, which still holds the old bank text.

## Operations follow-ups, Opus medium

- Sidebar: `/operations/runs` highlights Dashboard as well as Runs. Add an `exact` flag to `NavItem`. Consider starting Operations expanded.
- Client: let `apiSend` send headers such as `Idempotency-Key`, keep `error.details` on `ApiError`, and remove the direct `fetch` in `startRun`.
- Run now: inputs are JSON only, because no input schema is exposed.
- `RunTimeline` opens every failed step, not only the first. `AppPage` needs a way to put the status beside the title.
- `live.ts`: add a short delay before closing, so changing page does not reopen the socket.
- Recheck the final duplicate and cannot-run messages and the select's error ring in a browser. Review the screens in comfortable density and in dark and high contrast.
