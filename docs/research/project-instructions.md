# Project Instructions: Core Automation Tool on Elsa

## Goal
Build our core automation tool using Elsa Workflows (https://github.com/elsa-workflows, MIT-licensed, .NET) as the foundation. We are not building a workflow engine from scratch. We may modify parts of Elsa where it serves us better.

## Required capabilities
- Run C#, JavaScript and Python code, including their libraries (pandas, npm packages, etc.)
- Database access
- AI steps
- API calls
- Playwright (browser automation)

## Constraints
- Tools must be built in-house. Open-source libraries are fine; off-the-shelf products are not.
- Prefer extending Elsa (custom activities, modules, DI overrides, Studio modules) over patching core. Fork only when there is no extension point.
- If we fork: keep patches small and isolated, log every change and why, pin to a release, and rebase deliberately.

## Working approach
- Assume the person is a self-described beginner in programming: explain the "why" behind design choices, avoid jargon without explanation, and give concrete next steps.
- Keep the tone casual and conversational, not formal.
- Verify claims about Elsa against the actual code (elsa-core, elsa-studio, elsa-extensions) rather than relying on memory. Elsa versions change.
- Separate "already exists in Elsa", "extension point exists", and "needs a fork" whenever assessing a feature.
- Recommend the smallest end-to-end slice first, then expand.

## Repos likely to matter
- elsa-core: the workflow engine
- elsa-studio: the dashboard/designer (modular)
- elsa-extensions: integration packages
- elsa-guides / elsa-samples: example projects
- elsa-apps: Docker images for Elsa Server and Studio
- elsa-gitbook: current documentation


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- Goal: superseded. We do not build on Elsa or modify it. We build our own engine in Python and borrow Elsa's workflow concepts (`BUILD_PROMPT:125-166`).
- Required capabilities in the MVP: Python code via `run_python` (separate process); any existing program via `legacy_robot_wrapper`; database via the DB interface and python-oracledb; AI via `ai_extract` (off by default); API via `http_request`; Playwright via `playwright_robot` and `playwright_script` (Python). Running C# or JavaScript code is not in the MVP spec.
- Constraints: in-house, open-source libraries yes, products no, still apply. The fork rules no longer apply.
- Working approach: still applies (explain the why, casual tone, verify claims, smallest coherent build).
