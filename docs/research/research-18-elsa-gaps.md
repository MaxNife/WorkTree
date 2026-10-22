# Research 18: Elsa's own gaps (release vs main, security, retries, scheduling, single-node testing, data mapping, errors)

Status: research only, nothing built. Everything below comes from reading the `main` branch of elsa-core / elsa-extensions cloned on 2026-09-29 (a shallow clone: one commit, no tags, no history). Anything marked UNVERIFIED was not tested or could not be confirmed from that clone.

## 1. Release vs `main`, and the security findings

**What I could and could not check**
- The clone is `main` at a single commit (2026-09-29). No tags, no git history, so I cannot diff `main` against 3.8.0 or any release.
- The security assessment (`doc/security-assessment/elsa-workflows-elsa-core-findings-2026-05-20.md`) lists 25 findings against `release/3.7.0`: 13 HIGH, 12 MEDIUM.
- The 3.8.0 changelog in the repo (`doc/changelogs/3.8.0.md`) is short (16 lines) and lists no security fixes. So it neither confirms nor denies them.

**What `main` looks like for the HIGH findings I spot-checked**

| Finding (against 3.7.0) | On `main` |
|---|---|
| Admin API key = all-zero GUID | Fixed in code: `AdminApiKeyProvider` accepts nothing unless a key is explicitly configured; the all-zero key is marked development only |
| Admin user accepts any username with password `password` | Fixed in code: `AdminUserProvider` returns no user unless username and password are configured |
| Hardcoded JWT signing key in default config | Sample app now has a placeholder `CHANGE_ME_TO_A_SECURE_RANDOM_KEY` (still a placeholder to replace, not a secure default) |
| Password hashing unsalted single-pass SHA-256 | Changed: `DefaultSecretHasher` now uses PBKDF2-SHA256; a legacy SHA-256 path remains for old hashes |
| Role assignment on Users/Create | Now checks `CanAssignRolesAsync` |
| Unauthenticated bookmark resume body | A 1 MB body limit exists; the endpoint is still anonymous and protected by an encrypted token |
| Python.NET / Roslyn C# expressions unsandboxed | Disabled by default (`AllowHostCodeExecution`), and the host must opt in. Still not a sandbox once enabled |
| `x-download-id` path traversal (ZipManager) | The `ZipManager` file is gone from that path; the header name now appears only in `WriteFileHttpResponse`. Not verified beyond that |
| Polymorphic JSON deserialization (RCE) | NOT verified either way. I did not find an obvious allow-list in `PolymorphicObjectConverter.cs` on a quick grep. Needs a proper look |
| LocalHost permission handler grants admin | Handler file not found on `main` (may be removed or moved). Not verified |

**Bottom line:** `main` has clearly been hardened since May, but I cannot say which fixes are in a published 3.8.0 package. Anyone reviewing this will need a real answer, so the plan should be: pick a specific released version, pull its actual source (tag) and re-check each HIGH item, or pin to a commit of `main` we build ourselves. Either way the deserialization one (RCE class) needs a proper check.

## 2. Retries and resilience

**Already exists (verified)**
- `Elsa.Resilience` + `Elsa.Resilience.Core` (Polly under the hood). A node opts in by implementing `IResilientActivity` and calling `IResilientActivityInvoker.InvokeAsync(...)` around its work.
- Studio has a **Resilience tab** on activities and the module records each retry attempt (attempt number, delay, details) so Studio can show that retries happened.
- Strategies (retry count, delay, exponential/constant backoff, jitter) are defined in configuration (`Resilience:Strategies`) or in code, and picked per activity.
- Quartz job execution has transient retry support (per the 3.6.0 changelog).

**Gaps**
- Out of the box only the HTTP activities (`SendHttpRequestBase`) are resilient. SQL, CSV, file, SMTP etc. are not. So retries for our Oracle, Graph, Playwright and file nodes exist only if **we** implement `IResilientActivity` in those nodes. That is a clean extension point, not a fork.
- The only strategy shipped is `HttpResilienceStrategy` (handles `HttpRequestException`, timeouts, transient status codes). For Oracle or portal downloads we would write our own strategy classes.
- Default transient-exception detector matches exception *type names* exactly (e.g. `SqlException`, `NpgsqlException`, `DbException`, `TimeoutException`) plus message patterns ("timeout", "connection reset"...). `OracleException` is not in that list, so we would add our own `ITransientExceptionStrategy` (UNVERIFIED that Oracle messages would not already match patterns).
- Retry is *in-place*, inside one activity call. Retrying a whole workflow instance after failure is a separate thing: the Alterations module has a `retry` endpoint for faulted instances.

## 3. Errors, branching, loops

**Already exists (verified)**
- Control flow: `If`, `Switch`, `For`, `ForEach`, `While`, `Parallel`, `ParallelForEach`, `Fork`, `Break`, `Sequence`, `Flowchart` (drag-and-drop canvas with outcome connections), `StateMachine`, `Fault`.
- Activities can end with named outcomes (example: `DownloadHttpFile` completes with the outcome "Failed to connect"). In the Flowchart each outcome is a connection you draw.
- When an activity throws, an incident is recorded and an *incident strategy* decides what happens: `FaultStrategy` (workflow faults) or `ContinueWithIncidentsStrategy` (workflow continues, incident recorded).

**Gaps**
- I found **no Try/Catch activity** in core or extensions (grep for `Try`/`Catch` classes). There is no built-in "on error, go here" branch like Make's error handlers or n8n's error output. Our nodes can do this themselves: catch their own exceptions and complete with a "Failed" outcome, so the Flowchart can route it. That is a design rule for our node library, not something Elsa gives for free.
- `ForEach` over a very large list runs inside the workflow engine; for million-row data we already decided to keep data in files on the worker (research 04), not in loops.

## 4. Scheduling

**Already exists (verified)**
- Activities: `Cron` (CRON expression), `Timer` (interval), `StartAt` (specific time), `Delay`.
- Default scheduler is `LocalScheduler`: in-memory, in-process. Schedules are rebuilt from stored triggers/bookmarks at startup (`SchedulingBookmarkReconciler`). Past-due schedules after downtime are staggered (`PastDueScheduleStaggerer`) to avoid a burst.
- Optional Quartz.NET and Hangfire integrations exist in elsa-extensions (for clustering and persistence of jobs).

**Gaps / watch-outs**
- The Quartz EF Core packages exist for MySQL, PostgreSQL, SQL Server and SQLite. **No Oracle package** is listed. Quartz.NET itself can use Oracle, but Elsa's ready-made package does not (UNVERIFIED how much work a custom Oracle setup is).
- With several Elsa instances and the default local scheduler, each instance would schedule the same cron: we would need Quartz/Hangfire (or one scheduler instance) for exactly-once. To be settled when we decide the hosting shape.
- "Catch-up after downtime" behaviour (run missed schedules or skip) is a business decision to check with Hope's team; the staggering code suggests missed schedules are run on startup (UNVERIFIED for cron specifically).

## 5. Testing one node in Studio

**Already exists (verified)**
- Activity properties have a **Test tab** with a Start button that calls `POST /tests/activities`. The backend (`ActivityTestRunner`) builds an execution context for the workflow, schedules just that one activity, runs it, and returns status, activity state, outcomes, outputs and any exception. Studio shows them in panels.
- The request identifies the workflow by **definition version id** and the activity by node id. So the workflow must be saved (UNVERIFIED whether unsaved edits are ignored).
- Workflow variables can be given **test values** (`VariableTestValues`) which the runner sets before running.

**Gaps**
- It runs the node for real, with real side effects (sends the mail, writes the row). There is no dry-run mode.
- Only variables get test values. Outputs of upstream activities are **not** replayed, so an input that reads "output of step 2" would be empty unless step 2's output was stored in a variable that has a test value. (Inference from code, UNVERIFIED in the UI.) This is very different from n8n, where you "execute step" and get the upstream data pinned.
- Needs the test permission (`Tests` `Execute`) and would run on the server that has our node code.

## 6. Data mapping between nodes

**How it works today (verified)**
- Each activity has an **Outputs tab** where an output is bound to a **workflow variable** (or a workflow output), with a type and optional output converter.
- Downstream inputs are set with **expressions** in a chosen syntax (JavaScript, Liquid, C#, Python if enabled, or literal). JavaScript expressions can read `variables.X`, and generated helpers like `getResultFromSqlQuery()` (name pattern: `get{OutputName}From{ActivityName}`) and `getVariable(name)`, `getInput(name)`, `getOutputFrom(activityId, outputName)`.
- The Studio code editor is given generated TypeScript type definitions for workflow variables and these helpers, so you get **autocomplete inside a code editor** (`WorkflowVariablesTypeDefinitionProvider`).

**Gaps versus what Hope knows (Make / n8n / Power Automate)**
- No drag-and-drop **data pill picker** found: mapping is "write an expression", not "click the field from step 3". That is the biggest UX gap for non-coders, and we already need a custom Studio editor for conditional fields (research 14/15). A pill picker would be a custom Studio component (extension point, effort UNVERIFIED).
- Outputs are objects; nested field selection is by expression (`getResultFromX().rows[0].amount`).
- Passing file *references* between nodes (our design) means only small strings/paths travel through variables. That fits the variable model well.

## 7. Classification summary

| Need | Status |
|---|---|
| Orchestration, branching, loops, cron/timer | Already exists |
| Retries for our own nodes | Extension point (`IResilientActivity` + our strategies) |
| Error branches ("on failure go here") | Design rule in our nodes (named outcomes); no built-in Try/Catch found |
| Single-node test | Already exists (Test tab), with limits above |
| Data-pill mapping UX | Extension point (custom Studio editor), or accept expressions |
| Scheduler on Oracle / multi-instance | Open question: no Oracle Quartz package |
| Which released version is safe | Not resolved: needs tag-level check |

## 8. Open items
1. Pick a release (or `main` commit) to evaluate, and re-check the deserialization RCE finding on that exact source.
2. Decide hosting shape (one instance vs several) because it drives the scheduler choice.
3. Check with Hope's team what should happen to missed cron runs after downtime.
4. Prototype later (not now): does the Test tab work on unsaved changes; what an upstream-dependent input looks like when tested alone.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- Elsa release security findings do not affect us unless Elsa code is adapted (then check the adapted file).
- The concepts become our requirements (`BUILD_PROMPT:139-166`):
  - Resilience → per-step `retries` with every attempt recorded.
  - Errors → outcome routing plus incidents.
  - Scheduling → APScheduler with schedules rebuilt from the DB and staggered `catch_up`.
  - Alterations retry → "Retry from failed step".
  - Single-node test → "Run this step" with pinned upstream data.
  - Data mapping → output picker.
- Quartz/Oracle and multi-instance scheduler notes do not apply to the MVP.
