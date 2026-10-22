# Research 19: which language for which tool (2026-09-30)

## Why this note exists
Research 01 to 18 was mostly Python. Hope then said: the core runner is .NET (Elsa), nodes may be .NET, Python or JavaScript, chained nodes in different languages must work seamlessly, and each tool should be built in the language that handles it best. Rules from Hope:
- "Linear" tools (Excel, CSV, TXT, ZIP, HTML, Word, PPTX, log parsing): pick the single best language and build the WHOLE tool in it.
- Scripting tools (Playwright): may be multi-language.
Each research file (01 to 13) now ends with a "Language verdict" section holding the evidence. This note is the one-page summary.

## Verdicts
| Tool | Verdict | Confidence | Main reason (evidence in the file) |
|---|---|---|---|
| Excel (05) | Python | High | calamine reads 500k rows in 6.3 s (best JS: 20.5 s); only openpyxl kept every feature incl. the chart on edit; XlsxWriter richest writer. JS writes plain files about 3x faster; .NET unmeasured |
| CSV (06) | Python | Low (a tiebreak) | Requirement is anything you can do with a CSV. Python and JS both handled every messy-file and write case tested and both reach 0.6-0.9 s on 3M rows through the same engines (polars, DuckDB). Python wins on library maturity and team fit only. .NET (CsvHelper, DuckDB.NET) unmeasured: the most likely to flip this |
| TXT (07) | Python | Medium (narrow) | .NET is 2x faster at a raw line loop (0.74 s vs 1.43 s) but the gap is under a second; Python has fixed-width, encoding and pandas tested |
| ZIP (08) | Python | Medium | speed is a tie (zlib-bound); AES-256 proven in Python (pyzipper) and in one of four JS libraries; .NET built-in cannot open AES zips. Flips to .NET SharpCompress if legal refuses LGPL and 7z/RAR needed |
| HTML (09) | Python | Medium | cheerio and jsdom repair broken HTML as well as bs4, but `pandas.read_html` and Jinja2 make Python more convenient |
| Word (10) | Python | High | only Python can create AND edit arbitrary existing docs, extract and merge; JS can create and placeholder-patch; .NET low-level or licence-risky |
| PowerPoint (11) | Python | Low (close to JS) | one library for create and edit; JS pptx-automizer edits cleanly and is more active. Test both on the real template deck |
| Log parsing (12) | Python | Medium | polars 0.44 s; .NET fastest plain loop; Python best for multi-line records and follow-on analysis |
| Own logging (12) | .NET (Serilog) with a shared JSON format for all workers | Medium | platform plumbing; a contract, not a language race |
| LibreOffice (13) | Language-neutral | High | external process; called by the worker that owns the file tool |
| Playwright (01, 02) | Multi-language allowed (approved for any language): .NET for platform-owned login/download blocks; Python for project scripts | Medium | same core in every language (docs; Python wheel bundles the Node driver); Node and Python measured equal (1.43 s vs 1.38 s) |
| Graph: mail, OTP, files (02) | .NET | Medium (nothing run against a tenant) | official SDK GA and in the runner's language; JS SDK's newer generation is pre-release |
| Oracle (03, 04) | .NET | Low-medium (bulk-load speed unmeasured) | tied features across three Oracle-made drivers; fits Elsa's SQL activities; node-oracledb thin mode has documented gaps |

Update 2026-09-30 (later): Hope's answers (below) mean JavaScript is out for our own nodes and every verdict must also pass an operations checklist per file type.

Result: on day one only two runtimes are needed, .NET (runner, Graph, Oracle, Serilog, platform Playwright blocks) and Python (all file tools, log parsing, project Playwright scripts). JavaScript won nothing outright; its best showing was bulk Excel writes and PowerPoint template edits.

## What could and could not be measured
- Measured in this sandbox (2 cores, 8 GB, single runs, regenerated 3M-row test data): Excel 500k rows, CSV 3M rows, text/log 3M lines, ZIP 261 MB, whole-file-into-dictionaries memory. Python baselines were re-run on the same files.
- .NET: NuGet is blocked in the sandbox, so only built-in .NET 8 code ran (line streaming, hand-written CSV parsing, System.IO.Compression, dictionary-list memory). Every third-party .NET library (ClosedXML, ExcelDataReader, Sylvan, MiniExcel, CsvHelper, SharpCompress, AngleSharp, Open XML SDK, ShapeCrawler, Playwright for .NET, Graph and Oracle SDKs) is [docs] only. The .NET verdicts for Graph and Oracle are therefore leans, and the "Python wins" verdicts mean "Python is proven; .NET is unproven", not ".NET lost".
- Not measured anywhere: any Oracle load, any Graph call, Playwright for .NET, cross-language hand-off cost (process start plus JSON plus file), decimal/date/null behaviour across languages.

## How the older notes should be read
Notes 01 to 18, feasibility and the discussion summary say "Python worker" in many places (for example research-14 script mode, research-15 recommendation, research-16 way 2, research-17 "isolated Python worker"). That wording predates the .NET/Python/JavaScript decision. Read it as "the worker for the language that wins for that tool" using the table above. Research 14, 15 and 16 have a "Language update" section saying so; 17, 18, the feasibility note and the discussion summary were not edited.

## Decisions from Hope (2026-09-30, after the first version of this note)
1. **"Anything you can do with the file" applies to EVERY file tool**, not only CSV. Excel, Word, PowerPoint, ZIP, TXT/logs, HTML and PDF must each cover everything a person can do with that kind of file. Consequence: the verdicts above were judged on a short list of features and on speed. They are still the best evidence so far, but "Python wins" for Excel, Word, PowerPoint and ZIP now has to be re-checked against a full operations checklist per file type (see "What the answers change").
2. **Playwright is approved for any language.** The open question about the approval being tied to one language package is closed. Playwright can be chosen per script for speed and reliability, and .NET, Python and JavaScript are all allowed.
3. **Project nodes are written by a team of Python and .NET developers.** Nobody on the team works in JavaScript.

## What the answers change [reasoning]
- **JavaScript drops out as a language for our own nodes.** It won no tool outright (see the result line above), and a JavaScript node would have no maintainer. The real choice for every tool is now Python or .NET. JavaScript stays in the test plan for reference and only matters if some library is clearly better and someone is named to own it. This does not touch the separate requirement that workflows can RUN JavaScript snippets (Elsa expressions, a "Run Node" activity); that is about what workflow authors can run, not about the language our nodes are written in.
- **The "team fit" tiebreak no longer favours Python.** It was the deciding reason in CSV (low confidence) and part of the reasoning in TXT, HTML and PowerPoint. With Python and .NET developers both on the team it is neutral. CSV is therefore genuinely open between Python and .NET until CsvHelper, Sylvan and DuckDB.NET are measured. Excel, Word, ZIP and PDF still lean Python on evidence (features proven), not on team fit.
- **Project nodes vs platform nodes:** the earlier assumption (Python for project nodes, .NET for platform nodes) matches the team, so it stands. Where a tool is a linear tool, one team owns the whole tool in one language.
- **Playwright:** with the approval covering any language, use the language that is fastest and most reliable per script. Measured so far: Node and Python equal (1.43 s vs 1.38 s); .NET unmeasured. The rule "multi-language allowed for scripting tools" stays, but only Python and .NET are realistic for maintenance.
- **"Anything you can do with the file" needs a definition.** No library covers literally everything Excel or Word can do (macros, pivot refresh, exact print layout, tracked changes and so on). Working definition used in the test plan: for every file type there is a written list of operations; a language passes a file type when every operation on the list is done either by one of its libraries or by LibreOffice (research-13) called from that tool, and the operations nobody can do are listed as known gaps. The list and the coverage result are in the test plan (section "Operations checklist" and the `Coverage` sheet of RESULTS.xlsx).

## Open decisions for Hope
1. LGPL (py7zr, docxtpl, paramiko): acceptable to legal? It decides ZIP 7z support and Word templating. Still open.
2. LibreOffice (headless, as an external process) as a backstop for operations no library covers (recalculation, PDF conversion, .doc/.xls legacy formats, pivot tables and so on). Hope's position (2026-09-30): if it tests well, it can be used for office file types, so the test plan now evaluates it (research-20, area LO). Still to confirm with the organisation: the rule is "libraries yes, products no", and LibreOffice is an open-source program that the tool calls; its licence also needs legal.
3. Which runtimes (Python, .NET worker, Node) are already approved on the machines that would run automation? Node matters less now, but the runner machines must have Python and .NET.

## Suggested next research (not started)
1. Hand-off rules across a .NET -> Python -> JavaScript chain: money as strings or fixed-scale decimals, ISO 8601 dates, an explicit null rule, and a table file format between steps (Parquet or Arrow are the candidates; all three languages have libraries; not tested).
2. Cost of one language hop (worker process start, JSON, file hand-off): decides whether splitting a job over several nodes in different languages is affordable.
3. Re-run the Excel, CSV and ZIP benchmarks for .NET on a machine that can reach NuGet (ClosedXML, ExcelDataReader, Sylvan.Data.Excel, MiniExcel, CsvHelper, Sylvan.Data.Csv, DuckDB.NET, SharpCompress). Any .NET result that beats Python by a wide margin on a real workload would flip that tool.
4. Oracle bulk-load benchmark on a non-production instance: same 3M-row file, array insert and direct path, in each language.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:

| Tool | Python build |
|---|---|
| Excel, CSV, TXT/logs, ZIP | Python (CSV is no longer open vs .NET) |
| HTML, Word, PowerPoint | Out of MVP scope |
| Own logging | structlog JSON + correlation id |
| LibreOffice | External process, optional, off by default |
| Playwright | Python |
| Graph | Python (msgraph-sdk or direct REST; choice recorded in `DECISIONS.md`) |
| Oracle | python-oracledb thin |

- JavaScript: not used for activities. The frontend is Vue 3 + TypeScript by spec.
- Runtimes: Python at run time; Node.js only to build the frontend.
- Still open: LGPL, LibreOffice under "libraries yes, products no".
- Suggested research items 1-2 (cross-language hand-off) matter only when a non-Python worker is added; the Parquet-between-steps rule applies now. Item 3 (.NET re-benchmarks) is not needed. Item 4 (Oracle bulk load) is still needed, Python only.
