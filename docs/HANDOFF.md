# HANDOFF (Elsa reference): In-house core automation tool on Elsa Workflows

Written 2026-10-22 from research notes 01-20, the feasibility note, and the discussion summary (all dated 2026-09-29/30). This is the single briefing a coding agent should read first. Everything is research only: **nothing has been built or run yet**, and the Elsa findings come from reading `main` (elsa-core `8fadf47`, elsa-extensions `212dc55`), not a tagged release. **Status 2026-10-22: the build is now the Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`, started with `docs/AGENT_START_PROMPT.md`). This file is kept as the major Elsa workflow reference; do not follow its Elsa/.NET build instructions. Section 11 at the end maps every section to the Python build.**

## 1. Goal and constraints

- ~~Build the core automation tool on Elsa Workflows. Not from scratch.~~ **Superseded 2026-10-22:** build our own engine in Python/FastAPI, using **Elsa Workflows** (MIT, .NET, https://github.com/elsa-workflows) as the major workflow reference and n8n as a secondary reference for workflow behaviour and UX. Neither is a dependency.
- **Everything is built in-house.** Open-source libraries are fine. Off-the-shelf products are not.
- (Elsa track only; not applicable to the Python build.) Prefer extending Elsa (custom activities, DI overrides, Studio modules, `ISqlClient`, `ISecretStore`). Fork only if there is no extension point. If forking: small isolated patches, a change log, pin to a release, rebase deliberately.
- ~~Core runner is .NET (Elsa). Nodes may be .NET or Python.~~ **Superseded 2026-10-22:** the control plane, workers and all activities are Python. The job/result envelope stays language-neutral, so a .NET or other worker can be added later and chained seamlessly.
- Team is Python and .NET developers. **Nobody writes JavaScript**, so JS is out for our own nodes (workflows may still run JS snippets via Elsa expressions). Python build: activities are Python only; the frontend is Vue 3 + TypeScript by spec (`BUILD_PROMPT:71`), with the built bundle committed so running needs no Node.
- Playwright is approved for any language.
- Hope is the builder (self-described beginner, solutions developer: automation, AI, backend). Explain the why, keep it casual, give concrete next steps.
- Spec style rule from Hope: do NOT split the build into milestones or phases for the coding agent. The checkpoints in `docs/BUILD_CHECKPOINTS.md` are resume markers with git commits, not phases. The agent never stops at them.

## 2. Workload to support

Mostly: portal downloads, Oracle ETL, file CRUD, mail sending. Two reference projects:
1. Read Excel -> compute/format Excel/CSV -> deliver to network share or via Graph API.
2. ETL: download files from a portal -> format -> load to an Oracle table.

Files range from thousands to a few million rows. Oracle is "newer" (treat as 19c+, confirm). Portal logins vary: API token, plain form, browser login with MFA (mostly **email OTP**, read via Graph today). Push/SMS MFA cannot be unattended (use Elsa `UserTask` human-in-the-loop).

## 3. Architecture (Elsa version; Python mapping in section 11)

- **Orchestrator:** Elsa engine + Studio designer (.NET).
- **Workers:** each language step is a job sent to an isolated worker (own env, JSON in / JSON out, files by reference). Day one needs only **.NET and Python**.
- **Node contract (shared by all languages):** inputs = small JSON + file references in a per-run workspace; outputs = file references + small result summary; outcomes = Done / Failed (named outcomes so the Flowchart can route errors); timeout; correlation id; same structured JSON log fields everywhere. Secrets passed for one call only, never written to the shared workspace.
- **Never pass bulk data through Elsa variables.** `SqlQuery` returns a non-serializable `DataSet`; `ReadCsv` loads the whole file into dictionaries (3M rows = ~3.9 GB in .NET). Pass paths; workers stream in chunks (80-180 MB flat in every language).
- Shared per-run workspace storage is needed once there is more than one worker (same lesson as n8n queue mode).
- Node authoring routes in Elsa: (1) saved workflow as a node ("Usable as activity", no code, language-neutral), (2) catalogue-driven nodes published by workers via a custom `IActivityProvider`, (3) C# drop-ins via `Elsa.DropIns` (unverified; runs with the server's full access, so platform code only, project C# goes in a .NET worker).
- Node organisation: categories like "Platform / Excel", "Project X / ...". No project/folder concept in Elsa. Reuse means using a saved node as-is (no derive/override needed).
- Reusable nodes take **credentials as inputs** via the Studio secret picker, never hard-coded.
- UX target is n8n/Make-style: one node per file tool, operation dropdown, fields, saved connections. Elsa has no per-field show/hide, so use a custom Studio Blazor editor (effort unresearched) or `RefreshOnChange` dropdowns. Plus a separate "Run script" node (Python / C#) that runs in the worker, not in-process.

## 4. Language verdict per tool (evidence in research notes; .NET third-party libs were never run, NuGet was blocked in the sandbox). Superseded for the Python build: every tool is Python (section 11).

| Tool | Verdict | Confidence | Note |
|---|---|---|---|
| Excel | Python | High | calamine read, openpyxl edit (only one that kept the chart), XlsxWriter create, pandas/polars. 500k rows: read 6.3 s, XlsxWriter write ~34 s. Formulas need LibreOffice/Excel to calculate |
| CSV | Python (open vs .NET) | Low | polars/DuckDB 0.4-0.9 s on 3M rows. CsvHelper, Sylvan, DuckDB.NET unmeasured |
| TXT / logs parsing | Python | Medium | polars 0.44 s; fixed-width via `read_fwf(dtype=str)`; encodings declared per source |
| ZIP | Python | Medium | pyzipper (AES-256, MIT); py7zr is LGPL. Flips to .NET SharpCompress if legal refuses LGPL and 7z/RAR needed. Cap extracted size and file counts (zip bombs untested) |
| HTML | Python | Medium | bs4/lxml + `pandas.read_html`, Jinja2; JS pages go through Playwright |
| Word | Python | High | python-docx (+docx2python, mammoth, docxcompose). TOC fields need Word/LibreOffice. docxtpl is LGPL (else in-house placeholder replace) |
| PowerPoint | Python | Low | python-pptx; test against pptx-automizer on the real template deck |
| Own logging | .NET Serilog | Medium | workers emit the same JSON fields + correlation id |
| Playwright | .NET for platform login/download blocks, Python for project scripts | Medium | same core in every language, Node vs Python equal speed |
| Graph (mail, OTP, files) | .NET | Medium | `Microsoft.Graph` SDK GA; nothing run against a tenant |
| Oracle | .NET (ODP.NET `Oracle.ManagedDataAccess.Core`) | Low-medium | bulk-load speed unmeasured; flip only the bulk-load op to Python if benchmark shows a big margin |
| LibreOffice | language-neutral, external process | High | only on files we generate; own profile per worker, timeout, no network, macros off, low-privilege account, never in the Elsa process |

"Anything you can do with the file" applies to every file tool. No library does literally everything, so the working definition is a per-type operations checklist (Excel 49, CSV 45, TXT/logs 29, ZIP 29, HTML 22, Word 43, PPTX 35, PDF 28) where each op is done by a library or LibreOffice, and the rest are listed as known gaps. The benchmark plan (research-20, 321 tests, writes RESULTS.xlsx) was written but **not run**; verdicts are to be rewritten from its results.

## 5. What Elsa already has vs what we build (verified in code on `main`). Python build: read as the Elsa concepts to re-implement (`BUILD_PROMPT:139-166`).

**Already exists:** HTTP activities incl. `DownloadHttpFile`; `ReadCsv`; `SaveFile`/`OpenFile` (one global blob store); `SqlQuery`/`SqlCommand`/`SqlSingleValue` (MySql, PostgreSql, SqlServer, Sqlite); `CreateZipArchive` (no extract, no password); `SendEmail` (SMTP/MailKit); `RunPython`/`RunCSharp`/`RunJavaScript` (in-process, off by default via `AllowHostCodeExecution`, not a sandbox); `UserTask`; control flow (If, Switch, For, ForEach, While, Parallel, Fork, Flowchart, StateMachine); `Cron`/`Timer`/`StartAt`/`Delay`; Resilience module (Polly, HTTP activities only); Studio Test tab for single nodes; Secrets module with Studio picker; Quartz/Hangfire integrations.

**Missing, we build (all extension points, no fork found so far):**
- Excel read/write node (worker), Word, PPTX, ZIP extract/password, HTML, log parsing, CSV beyond small files: Python worker nodes.
- Oracle `ISqlClient` (inherit `BaseSqlClient`, supply `CreateConnection()`/`CreateCommand()`, register `client.Register<OracleClient>("Oracle")`; marker `:`, set `BindByName = true`). Plus bulk load (array insert / `executemany`, or direct path into staging then MERGE). No bulk insert in Elsa.
- Graph module: send mail, read OTP mailbox, upload files. OTP rules: record time before triggering login, poll for newer mail from the portal's sender, take newest, serialise logins per portal/mailbox, timeout + fresh-code retry. Scope the app to specific mailboxes with RBAC for Applications in Exchange Online (remove unscoped Entra consent).
- SFTP, Playwright activities/worker (separate container, non-root, `--ipc=host`, `--init`; `storageState` files are credentials, store locked-down).
- `IResilientActivity` + own strategies for Oracle, Graph, Playwright, file nodes; add `OracleException` to a custom transient-exception strategy.
- Error branches: no Try/Catch in Elsa, so every node catches its own exceptions and completes with a named "Failed" outcome.
- Optional: data-pill mapper (custom Studio editor); Oracle scheduler (no Oracle Quartz package; needed only if multi-instance).

## 6. Secrets design (Elsa version; Python version in section 11)

- Nodes reference a secret by **name**. Leaning: `ConfigurationSecretStore` first (stores only a config key, value read from `IConfiguration`: env vars + config.json, which is how the team works today). Custom `ISecretStore` only if env vars are decrypted at app level or a vault arrives.
- Avoid the default `EncryptedSecretStore` (static `EncryptionKey`, no re-encrypt tool).
- Graph auth = client secret (expires, so expiry is the rotation trigger; no auto-rotation in Elsa).
- Only users trusted to run host code should author workflows with `RunPython`/`RunCSharp` (they can read whatever the host can).

## 7. Risks and things to verify before trusting anything (items 1-3 are Elsa-only; section 11 says which still apply)

1. **Security:** the May 2026 assessment lists 13 HIGH findings against 3.7.0. `main` fixed most spot-checked ones, but **polymorphic JSON deserialization (RCE class) is unverified**, a LocalHost admin permission handler could not be found, and I cannot tell which fixes are in a published 3.8.0. Pick a release tag (or a commit we build), pull its source, re-check each HIGH item. Must be done before it goes near production.
2. Secrets masking: verify a resolved secret never lands in `ActivityExecutionRecord`, logs or Studio's execution view. Check default `LogPersistenceMode` for large outputs.
3. Oracle persistence for Elsa itself: `Elsa.Persistence.EFCore.Oracle` exists but the newer VNext persistence lists no Oracle. Check which is the future and supported DB versions.
4. ODP.NET licence text needs legal. LGPL (py7zr, docxtpl, paramiko) needs a ruling.
5. LibreOffice: licence OK (MPL-2.0) but "libraries yes, products no" needs an answer. Desktop Excel on a service account: licence unclear.
6. Missed cron runs after downtime: business decision (code suggests catch-up on startup, unverified).
7. Studio Test tab runs for real (no dry-run) and does not replay upstream outputs. Custom Studio Blazor editor effort is unknown. Drop-ins appearing live in Studio is untested.
8. Never measured: any Oracle load, any Graph call, any third-party .NET library, cross-language hand-off cost, decimals/dates/nulls across languages (rule to adopt: money as strings or fixed-scale decimals, ISO 8601 dates, explicit nulls, Parquet/Arrow between steps, untested).

## 8. Open questions for Hope

- Exact Oracle version and auth method (user/pass, wallet, TNS, TLS, Kerberos); triggers/FKs/global indexes on target tables.
- Who decrypts the "encrypted" env vars today (platform or app code)?
- Which portals need push/SMS MFA?
- Hosting shape (one Elsa instance or several) drives scheduler choice.
- Is a vault expected eventually?
- Which Excel features do real workflows use (pivots, macros, charts, external links)?
- Are Python and a .NET worker approved on the runner machines? (Python build: only Python is needed at run time; Node.js is needed only to build the frontend.)

## 9. Where to start (a single coherent build, not phases)

**Superseded 2026-10-22: start with `docs/AGENT_START_PROMPT.md`.** Original Elsa plan, kept for reference: Stand up Elsa Server + Studio from a pinned release in our own solution that references Elsa as packages (no fork), define the worker/node contract above, and build the pieces needed to run reference project 2 end to end through that contract: portal login (Playwright worker + Graph OTP), file download by reference, a Python transform worker, and the Oracle client + load. Reference project 1 then reuses the Excel node, a Graph file/mail node and the same contract. Keep credentials as picker inputs and every node returning Done/Failed outcomes.

## 10. Source notes (full evidence; keep these in the Project)

discussion-summary, project-instructions, feasibility-two-test-projects, research-01 portal login/MFA, 02 Graph OTP + Playwright hosting, 03 Oracle, 04 large files, 05 Excel, 06 CSV, 07 TXT, 08 ZIP, 09 HTML, 10 Word, 11 PPTX, 12 logs, 13 LibreOffice, 14 nodes per file tool, 15 n8n/Make/Power Automate vs Elsa, 16 growing node library, 17 secrets, 18 Elsa gaps, 19 language verdicts, 20 benchmark plan. The benchmark plan file itself (`benchmark-plan-all-languages.md`) was not among the attachments.

## 11. Python build alignment (added 2026-10-22)

Decision: build our own engine in Python/FastAPI (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX. Neither is a dependency. Read sections 1-10 as Elsa reference material, mapped as follows:

| Section | Status for the Python build | Python equivalent |
|---|---|---|
| 1 Goal and constraints | Goal and the .NET runner superseded. Still apply: in-house build, open-source libraries yes, products no; no JS for our own activities; Playwright approved; explain the why; no phases. | `BUILD_PROMPT:31-37` |
| 2 Workload | Unchanged | Acceptance A1 covers both reference projects against local fixtures (`BUILD_PROMPT:108`) |
| 3 Architecture | Concepts kept, implementation replaced | Elsa engine + Studio → FastAPI control plane + Vue 3 Workflow Studio. Language workers → Python worker processes. Node contract → job/result envelope + activity interface (`BUILD_PROMPT:47,55`). "Never pass bulk data through variables" → files by reference, Parquet tables. Shared workspace → per-run workspace folder. Node routes (saved workflow, catalogue, drop-in) → sub-workflow step with pinned version, plus auto-discovery from `activities/` and an extra folder. Credentials as picker inputs → secret dropdown. n8n-style UX → Studio with operation dropdowns and dependent fields. |
| 4 Language verdicts | All Python | Excel, CSV, TXT/logs, ZIP: same Python libraries (`BUILD_PROMPT:58`). Own logging: structlog. Playwright: Python. Graph: Python (msgraph-sdk or direct REST; the build agent chooses and records it in `DECISIONS.md`). Oracle: python-oracledb thin. LibreOffice: external process, optional, off by default. Word, PowerPoint, HTML: out of MVP scope (`BUILD_PROMPT:65`). |
| 5 Elsa exists vs build | Becomes the list of Elsa concepts to re-implement | `BUILD_PROMPT:139-166` |
| 6 Secrets | Same ideas, own implementation | Secret-store interface. Default env vars + config file (the `ConfigurationSecretStore` idea). Optional Vault adapter. Secrets referenced by name. No static encryption key. Graph client secret as before. |
| 7 Risks | 1 (Elsa security), 2 (Elsa masking), 3 (Elsa Oracle persistence): not dependencies any more. Masking is now our own A6 test. 4-5 (legal): LGPL and LibreOffice still open; ODP.NET no longer needed. 6 (missed cron): default skip, `catch_up` option. 7 (Studio test tab): our Studio pins upstream data. 8 (never measured): Oracle load and Graph calls still unmeasured → `KNOWN_GAPS.md`. | `BUILD_PROMPT:45,113`; `docs/BUILD_CHECKPOINTS.md` |
| 8 Open questions | Still open, except .NET worker approval (not needed) | `docs/SYSTEM_DESIGN.md` §13 |
| 9 Where to start | Replaced | `docs/AGENT_START_PROMPT.md`, `docs/BUILD_CHECKPOINTS.md`, `BUILD_PROGRESS.md` |
| 10 Source notes | Unchanged. Each research note ends with a "Python build update" section. | `docs/research/*.md` |
