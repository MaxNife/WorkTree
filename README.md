# WorkTree (Python/FastAPI MVP)

An on-premise automation control plane: a workflow engine, a worker/robot fabric and a governed
activity library. A Vue 3 console is planned but not built yet. Elsa (MIT) is the engine reference;
n8n is a reference for workflow behaviour and builder UX. Neither is a dependency.

- Process rules for the build agent: [`docs/AGENT_START_PROMPT.md`](docs/AGENT_START_PROMPT.md)
- Full specification: [`docs/BUILD_PROMPT_python_mvp.md`](docs/BUILD_PROMPT_python_mvp.md)
- Checkpoints and progress: [`docs/BUILD_CHECKPOINTS.md`](docs/BUILD_CHECKPOINTS.md), [`BUILD_PROGRESS.md`](BUILD_PROGRESS.md)
- Decisions and known gaps: [`DECISIONS.md`](DECISIONS.md), [`KNOWN_GAPS.md`](KNOWN_GAPS.md)

This is a work in progress. See `BUILD_PROGRESS.md` for the checkpoints that are actually verified.
The API and CLI exist; the `web/` console is not started.

## Quick start

```bash
uv sync
uv run uaf create-user --username admin --role admin --password 'choose-a-long-password'
uv run uaf serve --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. API docs are at `/docs`.

## Developer commands

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict app activities
uv run lint-imports
uv run pytest --cov=app --cov-report=term-missing
uv run uaf list-activities
uv run uaf verify-audit
```

The full runbook is still to be written; see `BUILD_PROGRESS.md` for the current state.
