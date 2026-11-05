Repository: WorkTree, a Python/FastAPI workflow automation platform. You are in your own git worktree. Work on the backend only.

GOAL
Fix the security defects recorded in `docs/SECURITY.md` and `tests/integration/test_security.py` (SEC-1 to SEC-9). The design of each fix is decided below; implement it. Each `xfail` test must become a normal passing test: remove its `xfail` marker and keep its assertion as strong as it is now.

DECIDED FIXES

SEC-1, High: Authors can reach the control-plane database through `db_url`.
- Add a class attribute on activities, `secret_only_inputs: tuple[str, ...] = ()`, and set it to `("db_url",)` on every SQL activity in `activities/sql.py`.
- A user who is not an Admin may not save a workflow, or use the single-step test endpoint, with a `secret_only_inputs` field that is anything other than exactly one `{{ secret:name }}` reference. Enforce this beside the existing `requires_admin_author` check in `app/services/workflows.py` and in the test endpoint in `app/api/system.py`. Refuse with a clear message.
- Defence in depth: at run time, whoever the author is, `open_database` refuses a SQLite URL that resolves to the control-plane database file. Pass the protected path to the activity child the way other child settings are passed. Compare resolved paths, so a relative or symlinked path cannot get around it. Also stop creating parent folders for a SQLite file.

SEC-3, High: `unc_archive` writes anywhere.
- Add a setting `activities.archive_roots: list[Path]`, default empty, with a commented example in `config.yaml`.
- `unc_archive` refuses a destination that does not resolve inside a configured root, and always refuses one inside `activities.extra_folder`, even if a root contains it. An empty list refuses every destination, with a message naming the setting.
- Test configuration may set `archive_roots` to the temp folders tests use. That is setup, not a weaker test.

SEC-2, Medium: long resource ids break audit verification. In `app/audit/writer.py`, truncate `resource_id` to the stored length before hashing, so the stored row and its hash agree. Refuse a secret name over 100 characters in the admin API with a 422.

SEC-5, Medium: password spraying.
- Keep the (username, address) limit.
- Add a per-address failure cap and a per-account failure cap across addresses, both as settings beside the existing limiter settings. Choose sensible defaults, higher than the existing per-pair limit, and state them in your summary.
- Purge expired buckets so memory cannot grow without bound.

SEC-6, Medium: refuse to start when `app.environment` is `prod` and `cookie_secure` is false, with a clear startup error. Do not silently force it on.

SEC-7, Low: `PUT` and `DELETE` on platform secret names through the admin API return 422, using `is_internal_secret`.

SEC-4, Low: activity children get an allow-list of environment variables instead of inheriting all `UAF_*` values. Keep what activities truly need, including the `UAF_CHILD_*` values, and confirm no activity loses something it reads.

SEC-8, Low: the `/api/events` socket re-checks the session at least every 15 s and closes with code 1008 when it has ended. It refuses a connection whose `Origin` is present and does not match the host, with the same close code.

SEC-9, Low: the 500 handler response carries the correlation id in the body and the same security headers as every other response.

NOT IN SCOPE: SEC-10 (secret scoping and host filtering) needs a product decision by the owner. Do not change it. Keep it documented in `docs/SECURITY.md`, and add it to `KNOWN_GAPS.md` as G17, in that file's table format.

ALSO
- Update `docs/SECURITY.md` so each fixed item reads as a protection with a `path:line` citation, and the findings list shows what is fixed.
- In `DECISIONS.md`, row 12.2 points at a G17 that was closed by row 12.6: remove that pointer. Add rows in section 12 for SEC-1 and SEC-3 and any other choice a reviewer needs to know.
- Regenerate anything these changes make stale: `uv run python scripts/export_openapi.py`, `scripts/gen_schemas.py`, `scripts/gen_data_model.py`, then `npm run api:generate` in `web/` if `docs/openapi.json` changed. Do not hand-edit generated files.

CONSTRAINTS
- Do not weaken, skip or delete any test. If an existing test relied on a hole, for example an Author saving a raw `db_url`, change who performs that step or use a secret reference, and list every such change in your summary.
- Do not touch `web/` apart from generated API types. Do not run `vite build`.
- No new dependencies.
- Repo traps: pytest config already adds `-q`, so do not add another. Tests use their own temp database; never touch `runtime/uaf.db` or read `runtime/secrets.json`. Scratch Alembic runs need `UAF_DATABASE__URL`, because `alembic -c` does not change the database. Files may be CRLF: keep each file's line endings. FastAPI here does not flatten routers into `app.routes`; use `app.openapi()`.
- Put helper scripts in files rather than quote-heavy heredocs, and delete scratch files before finishing.
- Do the work yourself: start no subagents.

DONE WHEN (run from the worktree root and report each)
- `uv run pytest --no-header -p no:cacheprovider` passes in full (about 8 minutes, with the pass count reported) and `tests/integration/test_security.py` has no xfail left except any you explain
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy --strict app activities`, `uv run lint-imports` pass

Commit on this worktree's branch with subject `fix(security): close the audit findings`, a body wrapped at 72 characters listing what changed and why, including that non-Admin authors must now use a secret reference for `db_url` and that `unc_archive` now needs `activities.archive_roots`, and the footer `Refs: CP-39`. Do not mention any AI or tool in the message, and add no Co-Authored-By trailer. Never use `--no-verify`. Do not push.

When finished, reply with what you changed for each SEC item, every existing test you changed and why, the limiter defaults you chose, anything you were unsure about, your worktree path and branch, and the commit hash.
