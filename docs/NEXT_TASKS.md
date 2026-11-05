# Next build tasks

Written 2026-11-05. Work these in order. Full briefs are in `docs/briefs/`.

## How to run them

- Keep two subagents running: Sonnet 5.5 high, plus a free OpenCode model (`opencode/` first, then `xkiro/`). Use Sonnet medium only when the free models fail.
- All UI work runs on Opus 5.5 medium.
- Start delegates one at a time. Six at once hit OpenCode's free limit.
- Review every result, rerun the gates, then cherry-pick to `main`. Do not push unless the owner asks.

## Check first: work that was still running

| Task | Thread title | Next step |
|---|---|---|
| CP-29 Operations | CP-29 Operations Console | Review, confirm the manual live-update check was done, cherry-pick. Rerun from `docs/briefs/brief-operations.md` if it did not finish |

## Queue

1. **SEC-10, Sonnet high, next.** Implement `docs/adr/0001-secret-usage-policy.md`: `credential_inputs`, `destination_inputs`, `allowed_hosts` and `environments` on secret metadata with a migration and Admin API, checks at save, at dispatch and in the test endpoint, egress filtering in `validate_url`, `secrets.enforce_policy` with the prod startup check, secrets listed on promotions, and a names-only secret list for the Studio dropdown. Run A1 and A6 with the policy enforced. Remove G17 when done.
2. **Live events after logout, small backend fix.** `/api/events` closes before accepting, so the browser sees 1006 and retries for ever. Accept, then close with 1008.
3. **CP-40 CI, free model.** Brief to be recreated from the checkpoint: `.github/workflows/ci.yml` and `docs/CI.md`.
4. **CP-37 A8 and A9 tests, free model.** `tests/acceptance/test_a8_a9.py`. Keep the real limits and report any miss.
5. **Studio graph logic, free model.** Pure TypeScript in `web/src/studio/`: definition to graph and back unchanged, auto-layout, safe edits, client validation.
6. **CP-30 Task Inbox, Opus medium.**
7. **CP-32 Admin, Opus medium.** Include the secret policy editor.
8. **CP-33 Pages and data views, Opus medium.**
9. **CP-31 Studio canvas, Opus medium.** Builds on task 5 and replaces `NodeCard`.
10. **CP-38 browser tests, then CP-41 docs and CP-42 final verification.**

## Waiting on the owner

- Push the commits on `main`, which is ahead of GitHub.
- Commit or drop `AGENTS.md`.
- Rename the `uaf` identifiers, or keep them.
- Replace the `lagos` timezone in `tests/integration/test_database.py`.
- Delete `worktree-original.bundle`, which still holds the old bank text.
