# What We've Discussed (2026-09-29)

## Starting point
- Wants to build a core automation tool using Elsa Workflows as the base (not from scratch).
- Elsa org: https://github.com/orgs/elsa-workflows/repositories (29 public repos; several archived).

## Wanted capabilities
C#, JavaScript and Python code (and their libraries), plus database, AI, API and Playwright.

## Feasibility: yes, all of it
**Easy / mostly built in**
- API: HTTP activities and webhook triggers
- C#: custom activities are plain C# classes; C# expressions exist
- Scheduling, durability, resuming after restarts
- AI and database: simple custom activities (extensions repo may already cover some)

**Needs building on top**
- Python and JavaScript: Elsa's built-in support is expression-level (small snippets, no pip/npm libraries). For real library support, build custom "Run Python" / "Run Node" activities that send code and inputs to an isolated worker (own venv / node_modules, JSON in and JSON out).
- Playwright: best run in its own worker/container (browsers are heavy), or as a custom C# activity.
- Sandboxing, per-workflow dependency management and secrets handling are not solved by Elsa. These are ours to build.

## Suggested shape
Orchestrator = Elsa engine + designer (.NET). Each language step is a job handed to a worker with JSON in/out. Start with one Python worker end to end, then add C#, JS and Playwright workers.

## Modifying Elsa
- MIT license allows forking and private changes (keep the license notice).
- Extend first: custom activities, modules/DI overrides, Studio modules.
- Fork only when core hard-codes something that can't be overridden. If forking: small isolated patches, change log, pin to a release, rebase deliberately, consider contributing generic fixes upstream.
- Rule of thumb: if it can live in our own project referencing Elsa as a package, do it there.

## Caveat
The Elsa details above are from general knowledge of Elsa 3 and haven't been checked against the code yet.

## Next steps
1. Create a Claude Project and paste in project-instructions.md.
2. Attach elsa-core, elsa-studio and elsa-extensions and check exactly what exists for scripting, AI and database.
3. List the specific bits to modify and sort them into "extension point exists" vs "needs a fork".
4. Prototype one Python worker activity end to end.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- "Orchestrator = Elsa engine + designer (.NET)" is superseded. The orchestrator is our FastAPI control plane and the designer is our Vue Workflow Studio.
- Still applies: each step runs as a job in an isolated worker (JSON in, JSON out, files by reference). This is now the job/result envelope (`BUILD_PROMPT:47`).
- Sandboxing, dependency management and secrets handling are still ours to build: `run_python` is process isolation, not a sandbox; secrets come from the secret store.
- "Modifying Elsa" no longer applies.
