# LICENSES

Runtime and development dependencies of the UAF MVP. Only permissive licences are used except
where noted. If a dependency is added or replaced, update this file in the same commit.

## Backend

| Package | Licence | Use |
|---|---|---|
| FastAPI | MIT | HTTP API |
| Starlette (via FastAPI) | BSD-3-Clause | ASGI toolkit |
| Uvicorn | BSD-3-Clause | ASGI server |
| Pydantic / pydantic-settings | MIT | boundary models, settings |
| SQLAlchemy | MIT | ORM and DB abstraction |
| Alembic | MIT | migrations |
| structlog | Apache-2.0 / MIT | structured logging |
| argon2-cffi | MIT | password hashing (argon2id) |
| itsdangerous | BSD-3-Clause | signed session cookies |
| APScheduler | MIT | cron scheduling |
| httpx | BSD-3-Clause | HTTP activities and fixtures |
| jsonschema | MIT | `ai_extract` result validation, published schema checks |
| PyYAML | MIT | workflow YAML |
| Jinja2 | BSD-3-Clause | fixture pages |
| python-multipart | Apache-2.0 | form uploads |
| websockets | BSD-3-Clause | live events |
| psutil | BSD-3-Clause | process-tree kill |
| pandas | BSD-3-Clause | chunked data processing |
| pyarrow | Apache-2.0 | Parquet |
| openpyxl | MIT | Excel edit |
| lxml | BSD-3-Clause | docx / xlsx XML editing |
| pypdf | BSD-3-Clause | PDF activity |
| XlsxWriter | BSD-2-Clause | large Excel output |
| pyzipper | MIT | AES-256 ZIP |
| python-calamine | MIT | fast Excel read |
| python-oracledb | Apache-2.0 | Oracle thin mode |
| **paramiko** | **LGPL-2.1** | SFTP (see `KNOWN_GAPS.md` G10; isolated, replaceable) |
| Playwright (Python) | Apache-2.0 | browser robots |
| hvac (optional) | Apache-2.0 | HashiCorp Vault |
| aio-pika (optional) | Apache-2.0 | RabbitMQ |
| opentelemetry-api/sdk (optional) | Apache-2.0 | tracing hooks |

## Frontend

| Package | Licence | Use |
|---|---|---|
| Vue 3 | MIT | SPA framework |
| Vue Router | MIT | routing |
| Pinia | MIT | client state |
| @tanstack/vue-query | MIT | server state |
| @vue-flow/core | MIT | Studio canvas |
| Vite | MIT | bundler |
| TypeScript | Apache-2.0 | type system |
| vue-tsc | MIT | type check |
| ESLint | MIT | lint |
| Vitest | MIT | unit tests |
| @vue/test-utils, jsdom | MIT | component tests |
| @vitejs/plugin-vue | MIT | Vite Vue plugin |
| typescript-eslint, eslint-plugin-vue, vue-eslint-parser, globals | MIT | ESLint rules |
| openapi-typescript | MIT | generated API types |
| @phosphor-icons/core | MIT | source of the copied icon paths (dev only); Phosphor Icons by Helena Zhang and Tobias Fried |
| @types/node | MIT | build-script types |
| @playwright/test | Apache-2.0 | E2E tests |

## Development only

| Package | Licence |
|---|---|
| pytest, pytest-cov, pytest-asyncio | MIT |
| Hypothesis | MPL-2.0 |
| mypy | MIT |
| ruff | MIT |
| import-linter | BSD-2-Clause |
| typeshed stubs (types-psutil, types-PyYAML, types-requests, types-jsonschema) | Apache-2.0 |
| pre-commit | MIT |
| pip-audit | Apache-2.0 |

## Notes

- No code, assets, icons or wording from n8n (Sustainable Use License) is used. n8n is a design
  reference only.
- No Elsa source was copied or adapted; Elsa (MIT) is a semantic reference only.
- The AI endpoint is internal and off by default; no external SaaS is called by the platform.
- Ported code: `activities/_formula/*` (the formula engine) is a Python port of GridCraft, and the
  mail-merge logic in `activities/_docx.py` follows WordCraft, both from CraftApps and both
  MIT OR Apache-2.0. The notice is kept in each ported module's docstring. No CraftApps binary is
  used or committed.
