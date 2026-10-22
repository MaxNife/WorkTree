# Research 14: one node per file tool (2026-09-29)

## Requirement from Hope (clarified)
Each file TOOL is one node in the workflow designer: an Excel node, a PowerPoint node, a Word node, and so on (Excel, CSV, TXT, ZIP, HTML, Word, PPTX, log; research-05 to 13). NOT one node per operation. So about 8 nodes, and each must cover almost everything that tool can do (what one does in pandas/polars/openpyxl or the app itself).
Hope knows Make, n8n and Power Automate and expects similar node behaviour (see research-15).

## What Elsa gives us for building a node (verified in code; nothing built or run)
- A node is a C# activity class with `[Activity]`, `[Input]`, `[Output]`. With only about 8 nodes, hand-written classes are the simplest route. (The `IActivityProvider` pattern that turns AI agents/workflows into nodes is only needed if the node count grows, and dependent option lists probably do not work on generated nodes.)
- Input settings: UI hint, dropdown options, order, category (groups fields into sections), default value, secrets flag, dynamic option handlers, read-only, browsable.
- Form controls: checkbox, checklist, code-editor, dictionary, datetime-picker, dropdown, dynamic-outcomes, expression-editor, json-editor, multiline, multitext, output-picker, outcome-picker, radiolist, singleline, type-picker, variable-picker, input-picker, workflow-definition-picker. No file picker, column mapper or cell-range picker.
- Conditional fields: NO per-field "show only when operation = X" setting in the core input model. But (1) dropdown/checklist/radio-list options can be recomputed from other fields' current values (`RefreshOnChange`), and (2) Studio supports custom editors: a module registers a UI-hint handler that renders any Blazor component. One JSON config input with a custom editor could show an operation dropdown with conditional fields. Blazor effort not researched. (Corrects an earlier version of this note that said forms are static.)
- Precedent for a code-editor node: `RunPython`, `RunJavaScript`, `RunCSharp`. The Python one only sets the editor language; the JavaScript one also supplies type definitions for autocomplete. `RunPython` runs inside the Elsa process via pythonnet, is off by default, and its own error text says it is not a sandbox.

## Ways to fit "almost everything" into one node (my reasoning)
A. Script mode: file reference(s) + a Python script in a code editor, run in the isolated worker with the tool's libraries preloaded. Covers nearly anything, and one node opens/saves the file once (avoids the repeated open/save cost in research-05). Arbitrary code runs in the worker, so the worker must be the sandbox (container, no secrets in its environment, restricted filesystem and network, timeouts).
B. Guided mode (n8n style): operation dropdown with fields per operation. No-code but each operation must be built.
C. Hybrid: guided operations plus "Run Python script" as one operation, and a separate general "Run Python" node.
Working recommendation now: guided-first (B/C), because Hope expects Make/n8n-style nodes (research-15).

## Shared contract for all tool nodes (proposal)
- Inputs: file reference(s) in a per-run workspace (not file contents: research-04), settings, timeout.
- Outputs: file reference(s) plus a small result summary (row counts, sheets, warnings). Outcomes: Done / Failed.
- Engines behind a node: the Python libraries by default; LibreOffice for recalculation/PDF on files we generate (research-13); desktop Office only if the licence question is answered yes.
- With several workers, the per-run workspace must be shared storage (n8n hits the same limit in queue mode).

## Earlier notes still valid
- Elsa persists activity outputs into execution logs unless excluded (research-04), so keep big values out of outputs.
- Repeated open/save on big workbooks is costly: openpyxl normal-mode load of 500,000 rows took 85 s and 2.1 GB; XlsxWriter write 32 s.
- LibreOffice calls are cheaper batched (sources: 5.96 s vs 13.52 s in their test).

## Open
- Which UX features matter most (research-15 open list).
- Effort for a custom Studio editor: not researched.
- Whether Studio shows these node forms acceptably: not tested.

## Language update (added 2026-09-30)
Hope's clarification: the core runner is .NET (Elsa), and nodes may be .NET, Python or JavaScript; chained nodes in different languages must work seamlessly. Every place above that says "Python worker", "Python script" or "the Python libraries by default" was written before this and should be read as "the language that wins for that tool". The per-tool winners are in research-19; the evidence is in each research file's "Language verdict" section.
What this changes here:
- Rule from Hope: a "linear" tool (Excel, CSV, TXT, ZIP, HTML, Word, PPTX, log parsing) is built in ONE language end to end, the one that handles it best. All eight came out Python (research-05 to 12). A scripting tool such as Playwright may be multi-language (research-01).
- Script mode (A/C above): the code-editor language is per tool. The Excel, CSV, TXT, ZIP, HTML, Word, PPTX and log nodes would take Python scripts; a Playwright script node could accept Python, JavaScript or C#.
- The shared contract above is what makes chaining across languages work: small JSON plus file references, the same outcomes, timeouts and correlation id in every language. The types that break across languages (money as decimals, dates, nulls) and the table-file format between steps (Parquet or Arrow is the likely candidate; not tested) still need their own research note.
- Each additional runtime (Python, Node, a .NET worker) is something the organisation must approve, patch and monitor. Today's verdicts need only .NET and Python on day one; JavaScript is not the winner for any tool tested.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- One node per file tool stands: `csv`, `excel`, `zip`, `txt_log` (and `sftp`) are each one activity with a Resource/Operation dropdown and per-operation fields (`BUILD_PROMPT:168-178`).
- Elsa Studio form controls are replaced by our Studio properties panel, generated from each activity's pydantic schema, with dependent fields, an output picker and a secret dropdown (`BUILD_PROMPT:80`).
- Script mode → `run_python`. The shared node contract → the job/result envelope. All activities are Python.
