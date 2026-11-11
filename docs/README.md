# WorkTree documentation

Written 2026-11-11 from a full review of the repository. This folder replaced the earlier `docs/`
on the same day (it was drafted as `docs_new/` and renamed).

## Read in this order

| # | Document | What it is |
|---|---|---|
| 1 | [01-product-overview.md](01-product-overview.md) | What WorkTree is, who uses it, the ideas, where it stands today |
| 2 | [02-system-design.md](02-system-design.md) | The **target** system design: a better design than today's, not a description of it |
| 3 | [07-nodes-and-connectors.md](07-nodes-and-connectors.md) | App connectors (Spreadsheet, PDF, Database...) and skill nodes (Match, One-time code...): how they are built, how data flows, how they look and behave |
| 4 | [03-upgrade-guide.md](03-upgrade-guide.md) | What the code does today, every defect found, and the phased path to the target design |
| 5 | [04-ui-reimplementation-guide.md](04-ui-reimplementation-guide.md) | The full UI redesign: every screen, action and behaviour, and how each should feel |
| 6 | [05-logo-redesign.md](05-logo-redesign.md) and [logo/](logo/) | The Bloom logo: files, construction, colours, rules |
| 7 | [06-database-and-security-plan.md](06-database-and-security-plan.md) | Target schema, migrations, retention, backup; threat model and prioritised controls |

## Also here

| Path | What it is |
|---|---|
| [model-guide.md](model-guide.md) | Which Claude model and effort to use for each phase, and which OpenCode and xkiro models answered when tested |
| [mockups/redesign-options.html](mockups/redesign-options.html) | The redesign review sheet (palette, three logo options, nodes, three screens). Published privately at https://claude.ai/artifact/UHeAjmZnPsNkTXFLg7uQZd |
| [Make.com, n8n, and Power Automate Modules Reference Guide.md](Make.com,%20n8n,%20and%20Power%20Automate%20Modules%20Reference%20Guide.md) | The owner's comparison of the three platforms; an input to document 07 |
| [reference/](reference/) | Files that tools and tests read: `openapi.json`, `schemas/`, `ACTIVITIES.md`, `DATA_MODEL.md` (all generated), plus `ENVELOPE.md`, `WRITING_AN_ACTIVITY.md` and `COMMIT_GUIDELINES.md` |
| [design-source/canvas-design/](design-source/canvas-design/) | The earlier design board, its source files and the owner's reference screenshots. Kept for reference; it was never committed to git, so this is the only copy |

## Design decisions made on 2026-11-11

The owner reviewed the mockup sheet and decided: theme is plant, nature, vibrant and colourful (not
green and brown); vivid colour on a light base; the seven-flower palette; the Bloom logo; plant
shapes for nodes, restyled as solid flowers; a colour band per area with coloured cards; device
fonts only. Document 04 section 15 lists what is decided and what is still open.

## What reads from this folder

Code depends on `docs/reference/`. Do not move or rename it without changing these:

| File | Reads or writes |
|---|---|
| `scripts/export_openapi.py` | `docs/reference/openapi.json` |
| `scripts/gen_schemas.py` | `docs/reference/schemas/` |
| `scripts/gen_activity_docs.py` | `docs/reference/ACTIVITIES.md` |
| `scripts/gen_data_model.py` | `docs/reference/DATA_MODEL.md` |
| `tests/contract/test_activity_contract.py` | `docs/reference/schemas/envelope-v1.json` |
| `tests/unit/test_workflow_validator.py` | `docs/reference/schemas/workflow-v1.json` |
| `tests/integration/test_api.py` | `docs/reference/openapi.json` |
| `web/scripts/generate-api.mjs` | `docs/reference/openapi.json` |
| `.pre-commit-config.yaml` | `docs/reference/openapi.json` |
| `CLAUDE.md`, `AGENTS.md` | `docs/reference/COMMIT_GUIDELINES.md`, `docs/04-ui-reimplementation-guide.md` |

## What the earlier folder held that is not here

All of it is in git history: the 20 research notes, `HANDOFF.md`, `BUILD_PROMPT_python_mvp.md`,
`BUILD_CHECKPOINTS.md`, `AGENT_START_PROMPT.md`, `NEXT_TASKS.md`, `UI_reference_list.md`, the old
`SYSTEM_DESIGN.md` and `SECURITY.md` (their still-true content is folded into documents 03 and
06), `design-language.md` (replaced by document 04) and `adr/0001-secret-usage-policy.md` (its four
rules are in document 06 section B3 and document 02 section 9.3).
