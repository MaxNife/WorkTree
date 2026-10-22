# Research 15: what Hope expects from tool nodes (Make / n8n / Power Automate) vs what Elsa offers (2026-09-29)

## Context
Hope has never used Elsa but uses Make, n8n and Power Automate and is familiar with how tool nodes work there. Target UX = those tools: a node per tool, pick an operation, fill fields, map data from earlier nodes, choose a saved connection. (Constraint: off-the-shelf products are not allowed, so those tools are UX references only.)

## How the reference tools structure file nodes (docs read; not exhaustive)
- n8n, Extract From File node: 11 operations chosen inside one node (CSV, HTML, JSON, ICS, ODS, PDF, RTF, text, XLS, XLSX, file to base64); reads a file from an earlier node's "binary" field.
- n8n, Convert to File node: 10 operations (CSV, HTML, ICS, JSON, ODS, RTF, text, XLS, XLSX, base64 to file), common options file name, output field, header row, encoding.
- So in n8n file handling is split by direction (extract vs convert), not one node per format, and the two pages I read list no Word or PowerPoint operations. "An Excel node, a PowerPoint node" is a different, richer split than n8n's.
- n8n node forms: `displayOptions` (show a field only for chosen resource/operation values) plus a Resource and Operation pair of dropdowns; this is how "pick an operation and the fields change" works.
- Power Automate, Excel Online (Business) connector: 15 separate actions (add/update/delete/list rows, tables, worksheets, comments, run Office Script). Limits: 25 MB files, 256 rows returned by default (pagination), 5 MB per request, 100 API calls per connection per 60 s, no pivot tables, no concurrent edits, one filter per column. A Python-backed node would not have these caps (research-05 measured 500,000-row workbooks).
- n8n binary data: kept in memory by default (can crash on large files); `filesystem` mode is recommended; queue mode (several workers) cannot use filesystem mode, so it needs database or S3 storage. Parallel to our design: pass file references, and with several workers the storage must be shared.
- Make: not researched.

## What Elsa offers for the same UX (verified in code, not run)
| Feature you expect | Elsa |
|---|---|
| Node per tool with typed fields, groups | Yes: activity class with inputs/outputs, category grouping |
| Operation dropdown that shows/hides other fields | NOT built in: no per-field show/hide setting in the core input model. Two workarounds exist (below) |
| Dropdown whose options depend on other fields (e.g. sheet names after choosing a file) | Yes: `RefreshOnChange` on dropdown/checklist/radio-list option providers; Studio posts the current values of all fields to `/descriptors/activities/{type}/options/{property}` and refills that field. It works on hand-written C# activity properties (the server resolves the provider from the property), so probably not on dynamically generated nodes (my reasoning, untested) |
| Fully custom editor for a field | Yes: Studio lets a module register a UI-hint handler that renders any Blazor component (`Elsa.Studio.Secrets` does this for its secret picker). One JSON "config" input with a custom component could show an operation dropdown and conditional fields (my reasoning; needs Blazor work; effort not researched) |
| Pick a saved connection/credential from a dropdown | Partly: Studio has a secret picker and Elsa has Secrets and Connections modules (research on secrets still to do) |
| Map data from earlier nodes | Elsa uses expressions plus output and variable pickers. A drag-and-drop "data pill" mapper like Make/Power Automate: not verified |
| Test a single node with sample data, see each node's output | Not researched |
| Loops, routers, error branches, retry-on-fail | Not researched (Elsa Resilience and flow activities exist) |
| A "Code" escape-hatch node | Yes: Elsa has `RunPython`, `RunJavaScript`, `RunCSharp` (in-process, disabled by default); ours would run in the isolated worker |

## Working recommendation (my reasoning)
n8n-style tool nodes with an operation dropdown, backed by the Python worker, plus a separate "Run Python" node for anything the operations do not cover (n8n's Code node is separate too). Conditional fields via a custom Studio editor. Keep "script" as one operation inside a tool node for people who want it.

## Open
- Which of these Hope leans on most in Make/n8n/Power Automate: mapping data from earlier nodes, testing a single node, connections dropdown, routers/iterators, error handling, templates?
- Effort of a custom Studio editor and of a data-mapping UI: not researched.

## Language update (added 2026-09-30)
The recommendation above says "backed by the Python worker" and "Run Python" because only Python had been researched. With the core runner in .NET and nodes allowed in .NET, Python or JavaScript, read it as: each tool node is backed by the language that won for that tool (research-19: the eight file tools and log parsing are Python; Oracle, Graph and platform plumbing lean .NET; Playwright is multi-language). The separate escape-hatch node becomes "Run script" with a language choice (Python, JavaScript, C#), as n8n's Code node offers more than one language. Elsa's built-in `RunPython`/`RunJavaScript`/`RunCSharp` remain in-process and off by default; ours would run in the isolated worker for that language.
The n8n comparison also gives a useful warning: n8n's queue mode needs shared binary storage, and so will several workers of different languages here (same per-run workspace, research-14).


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The n8n/Make/Power Automate expectations remain the UX reference. n8n is also a reference for workflow behaviour (`BUILD_PROMPT:168-184`).
- The "Elsa" column lists what Elsa lacks, which our Studio must provide: conditional fields, an output (data-pill) picker, a single-step test with pinned upstream data, and error branches via `on_failed`.
- Per-area UI references are in `docs/UI_reference_list.md`.
