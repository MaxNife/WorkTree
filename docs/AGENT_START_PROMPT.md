# AGENT_START_PROMPT: build the UAF Python/FastAPI MVP

Paste the block below into a new coding-agent session opened at the repository root (`c:\Users\USER\Code\Workflow-Builder`). The same block works for the first start and for every restart.

```text
You are the build agent for the WorkTree MVP in this repository.
Follow docs/AGENT_START_PROMPT.md exactly: read it now, then BUILD_PROGRESS.md,
then continue the build from the current checkpoint. Do not stop at checkpoint
boundaries and do not ask me questions. Work until every checkpoint in
docs/BUILD_CHECKPOINTS.md is done, committing to local git as you go.
```

---

## 1. Your job
Build the complete MVP specified in `docs/BUILD_PROMPT_python_mvp.md`:
- a Python 3.11+/FastAPI control plane, workers and activity library;
- a Vue 3 + TypeScript frontend;
- local fixtures and tests;
- the documentation set.

Elsa is the major workflow reference and n8n is a reference for workflow behaviour and UX (`BUILD_PROMPT:125-191`). Neither is a dependency.

## 2. Read before doing anything (first start and every restart)
1. `BUILD_PROGRESS.md` (repository root): where you are.
2. `docs/BUILD_CHECKPOINTS.md`: what each checkpoint must deliver and its "Done when" test.
3. `docs/BUILD_PROMPT_python_mvp.md`: the full spec. It is the authority when documents disagree.
4. `docs/SYSTEM_DESIGN.md`: repository map, do-not-break rules R1-R36, open questions.
5. As needed for the current checkpoint: `docs/HANDOFF.md` (the Elsa reference), `docs/UI_reference_list.md`, and `docs/research/*.md`. Read the "Python build update" section at the end of each research note before using it.

On a restart, read items 1-2 in full. Then read only the parts of items 3-5 that the current checkpoint needs.

## 3. Resume procedure (run at every start)
1. Run `git status` and `git log --oneline -15`. If the folder is not a git repository, you are at CP-00.
2. Open `BUILD_PROGRESS.md` and read "Current position" and "Work in progress".
3. If the working tree has uncommitted changes, inspect them (`git diff --stat`, then the relevant diffs).
   - If they belong to the current checkpoint and are coherent, keep them and continue.
   - If they are broken half-edits, finish or revert them. Never discard work without reading it.
4. Re-run the "Done when" checks of the last checkpoint marked `done`. If they now fail, fix that first.
5. Continue with the "Next action" in the tracker.

## 4. The work loop (repeat until CP-42 is done)
1. Set the current checkpoint to `in-progress` in `BUILD_PROGRESS.md`. Write its sub-steps under "Work in progress" and update "Next action".
2. Build the sub-steps. Run code and tests as you go.
3. **Interim commits:** commit whenever a sub-step works, and in any case at least every 30-45 minutes of work or after about 300 changed lines, whichever comes first. Use the message `wip(cp-NN): <what now works>`. Update "Work in progress" and "Next action" in the same commit.
4. When every "Done when" item passes, record each command and its result in the tracker table, set the status to `done`, clear "Work in progress", and set "Current checkpoint" to the next ID.
5. Make the checkpoint commit with the exact message given in `docs/BUILD_CHECKPOINTS.md` (`cp-NN: ...`). Then create a local tag: `git tag cp-NN`.
6. Go straight to the next checkpoint. **Do not pause, summarise for approval, or wait for input.**

## 5. Never-stop rules
- Checkpoints are resume markers, not stages. The build is one continuous piece of work (`BUILD_PROMPT:3`).
- Do not ask the user questions. When something is unclear, including any [UNKNOWN] in `docs/SYSTEM_DESIGN.md` §13, pick the simplest reasonable option, write it in `DECISIONS.md` with the reason, and continue.
- If something cannot be verified locally (real Oracle, Graph tenant, portals, Vault, RabbitMQ), verify it against the fixtures, add the gap to `KNOWN_GAPS.md`, and continue.
- If a checkpoint is blocked:
  - record the blocker and your workaround under "Blockers and workarounds";
  - set its status to `blocked`;
  - move on to the next checkpoint that does not depend on it;
  - come back to the blocked one when it can be unblocked.
  - Never mark a checkpoint `done` when its tests fail.
- Stop only when CP-42 is `done`, or when nothing left is buildable without an external decision. In that second case, write the reason in the tracker and in your final message.

## 6. Git rules
- **Local repository only.** Never add a remote and never push.
- If `git config user.name` or `user.email` is empty, set a **repo-local** identity: `git config user.name "UAF Build Agent"` and `git config user.email "uaf-build-agent@localhost"`. Do not change global git config.
- Make small, frequent commits with clear messages (`cp-NN: ...` for checkpoint commits, `wip(cp-NN): ...` for interim ones). Every commit that changes progress also updates `BUILD_PROGRESS.md`.
- Never rewrite history: no `--amend` on earlier commits, no rebase, no `reset --hard`, no force operations. Fix problems with a new commit.
- Commit messages follow `docs/COMMIT_GUIDELINES.md` (Conventional Commits, author Hope, never any AI attribution); it supersedes the `cp-NN:` and `wip(cp-NN):` message formats above.
- Never skip hooks (`--no-verify`). If a pre-commit hook fails, fix the cause and commit again.
- Never commit any of these:
  - secrets, `.env` files with values, or Playwright session state;
  - databases, run workspaces or logs;
  - `node_modules/` or `.venv/`;
  - generated large fixture data.
- **Do** commit `uv.lock`, `package-lock.json`, and the built web bundle (`BUILD_PROMPT:71`).
- Before each commit, run `git status` and check that the staged files are the ones you meant to stage.

## 7. Tracker rules (`BUILD_PROGRESS.md`)
- Keep "Current position" true at all times. **Before any long-running command** (big test suites, builds, data generation), make sure "Next action" says what you are about to do, so an interruption leaves a correct resume point.
- In the checkpoint table, fill in "Commit" with the short hash and "Verified by" with the commands you ran and their results (for example `pytest tests/unit -q → 142 passed`).
- Append one row to "Session log" each time you start a session and each time you finish a checkpoint.
- Keep the tracker factual. Never record something as working if you did not run it.

## 8. Quality rules that apply to every checkpoint
- Follow the engineering standards (`BUILD_PROMPT:91-99`): `mypy --strict`, `ruff`, TS strict, tests with failure paths, a deterministic clock, and coverage that grows toward ≥ 85% on `app/`.
- Keep to the do-not-break rules R1-R36 in `docs/SYSTEM_DESIGN.md` §11. In particular:
  - no secret outside the secret store;
  - files by reference;
  - activities never raise;
  - append-only audit;
  - the SoD rules.
- Every new dependency goes in `LICENSES.md`. Prefer MIT/BSD/Apache, and avoid GPL/LGPL where an alternative exists.
- Never copy code, icons or wording from n8n or any product in `docs/UI_reference_list.md`. Elsa code (MIT) may be adapted only with its notice kept and an entry in `DECISIONS.md`.

## 9. Environment notes (checked 2026-10-22)
- Windows 11. Both PowerShell and Git Bash are available. Use forward slashes in scripts that must run on both Windows and Linux.
- Installed: git 2.55, uv, Node.js + npm, and Python 3.14 at `C:\Python314`. If a required package has no wheel for 3.14 (python-calamine, pyzipper, playwright, oracledb), use `uv python install 3.12`, pin it in `pyproject.toml`, and record the choice in `DECISIONS.md`.
- Playwright browsers must be installed for the fixtures and E2E tests (`uv run playwright install chromium`). If the network blocks this, log it and continue with the other checkpoints.
- No global git identity is configured (see §6).

## 10. Definition of done
- Every checkpoint CP-00 to CP-42 in `BUILD_PROGRESS.md` is `done`, or is `skipped-gap` with an entry in `KNOWN_GAPS.md`.
- Every acceptance item A1-A10 (`BUILD_PROMPT:106-117`) is green and its evidence is recorded.
- The tag `mvp-complete` exists and `git status` is clean.
- Your final message gives:
  - what runs;
  - what was only tested against fakes;
  - the exact start commands;
  - pointers to `DECISIONS.md` and `KNOWN_GAPS.md`.
