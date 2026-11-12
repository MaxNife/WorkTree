# WorkTree

An on-premise automation platform for an operations or finance team: workflows built from reusable
steps, run on a schedule or on demand, paused for human decisions, with a full audit record. Python
3.12 and FastAPI on the server, a Vue 3 console in `web/`, SQLite by default.

- Documentation, in reading order: [`docs/README.md`](docs/README.md)
- Upgrade plan and current defects: [`docs/03-upgrade-guide.md`](docs/03-upgrade-guide.md)

Work in progress. The engine, workers, triggers, tasks, audit and the API are built; the console has
sign-in and Operations, and the other areas are placeholders (see `docs/01-product-overview.md`).

## Quick start

Needs [uv](https://docs.astral.sh/uv/) and, for the browser activities, Chromium.

```bash
uv sync
uv run playwright install chromium
uv run uaf db upgrade
uv run uaf create-user --username admin --role admin --password 'choose-a-long-password'
uv run uaf serve --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. API docs are at `/docs`. Settings are in `config.yaml`; any setting
can be overridden with a `UAF_` environment variable (for example `UAF_DATABASE__URL`).

## The database schema

Alembic migrations are the only way a database gets its tables. `serve`, `create-user`, `run` and
`verify-audit` refuse to start when the database is behind and name the command to run.

| Command | What it does |
|---|---|
| `uv run uaf db upgrade` | Migrate to the latest revision. A database built by an older WorkTree without migration history is adopted only if it matches exactly; otherwise nothing is changed and the differences are listed |
| `uv run uaf db current` | Show the current and latest revision |
| `uv run uaf db check` | Exit non-zero unless the database is at the latest revision and matches the models |

Back up the database file before upgrading.

## Secret policies

Each secret says where it may be sent and in which environments (dev, test, prod). An empty
policy refuses every use, so after the upgrade that adds policies every existing secret is
refused until you set one; `uaf db upgrade` lists the secrets affected.

```bash
uv run uaf secrets list
uv run uaf secrets policy portal_password --env dev test --hosts portal.example.com
uv run uaf secrets policy archive_password --env dev          # a local-only secret: no hosts
```

A secret created through the Admin API starts as dev only, with no hosts. Activities also cannot
reach loopback, link-local or cloud metadata addresses (`egress.denied_networks`). For local
development only, `UAF_SECRETS__ENFORCE_POLICY=false` turns the host and environment checks
off; a server with `app.environment: prod` refuses to start that way.

## Developer commands

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict app activities fixtures
uv run lint-imports
uv run pytest --cov --cov-report=term          # about 20 minutes
uv run pip-audit --skip-editable
npm --prefix web ci
npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web test
```

`pre-commit run --all-files` runs most of these. The CI workflow is parked in `ci/` until the app
build is finished (see `ci/README.md`).
