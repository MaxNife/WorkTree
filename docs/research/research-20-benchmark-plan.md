# Research 20: benchmark plan for Claude Code (2026-09-30)

Status: WRITTEN, NOT YET RUN. Nothing in it has been measured by the author; every result will come from Hope's own machine.

## What it is
One markdown file, `benchmark-plan-all-languages.md`, that Claude Code (any model) follows on Hope's machine. It extracts a test kit from its own appendix, runs the tests, and builds `RESULTS.xlsx` (16 sheets) plus `HANDBACK.md`.

## Size
- 321 tests: 121 Python, 105 .NET, 95 JavaScript. 166 timing tests (3 fresh-process runs, wall time and peak memory) and 155 capability tests.
- 133 test programs are provided (124 reference, 9 .NET starters that need NuGet and were never compiled); 188 are written by the executing model from the specifications.
- Areas: Excel, CSV, TXT and logs, own logging, ZIP, HTML, Word, PowerPoint, PDF, Playwright, HTTP, SMTP, SFTP, JSON/XML/Parquet, SHA-256 and PGP, LibreOffice, hand-off between languages, Oracle (optional).

## Operations checklists (added after Hope's decision)
Hope's requirement "anything you can do with the file" applies to every file tool. Each file type has a written list of operations in `ops/`: Excel 49, CSV 45, TXT and logs 29, ZIP 29, HTML 22, Word 43, PowerPoint 35, PDF 28 (280 in all). Every candidate library is tried on every operation; a result of yes must be verified by reading the output back. The workbook sheets `Coverage` and `Coverage summary` show, per operation and language, what can be done, which libraries do it, and which operations are gaps.

## LibreOffice as a candidate (added at Hope's request)
Area LO plus three `*.OPS.PY.libreoffice` tests (Excel, Word, PowerPoint) evaluate LibreOffice for office files: coverage of the same operations checklists (command line and UNO API, helper `py/lo.py`), a 26-pair conversion matrix incl. legacy formats and passwords, round-trip fidelity, and reliability and speed. It has its own column in the Coverage sheet. Decision rule is in section 4b of the plan.

## Decisions that shaped it
- Team is Python and .NET developers: JavaScript is tested for completeness but run last; it is not a realistic choice for our own nodes (research-19).
- Playwright is approved for any language.
- Still open: LGPL acceptability (py7zr, docxtpl, paramiko); whether LibreOffice as a called program is acceptable under the "libraries yes, products no" rule (Hope: fine if it tests well).

## Next
Hope runs the plan, sends back RESULTS.xlsx, the results folder and HANDBACK.md; the verdicts in research-01 to 13 and research-19 are then rewritten from measured data.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- For the MVP only the Python tests, area LO (LibreOffice) and the optional Oracle area matter. The .NET and JavaScript tests are not needed.
- The plan file is still absent from the repository and still not run. The MVP's own performance budgets are asserted in its tests (`BUILD_PROMPT:99,115`).
