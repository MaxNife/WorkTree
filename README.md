# WorkTree (Python/FastAPI MVP)

An on-premise automation control plane: a workflow engine, a worker/robot fabric and a governed
activity library. A Vue 3 console is planned but not built yet. Elsa (MIT) is the engine reference;
n8n is a reference for workflow behaviour and builder UX. Neither is a dependency.

- Documentation, in reading order: [`docs/README.md`](docs/README.md)
- Upgrade plan and current defects: [`docs/03-upgrade-guide.md`](docs/03-upgrade-guide.md)
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
