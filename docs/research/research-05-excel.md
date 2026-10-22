# Research 05: Excel (2026-09-29)

## Requirement set by Hope
For EACH file type (Excel, CSV, TXT, ZIP, HTML, Word, PPTX, log) the tooling must let the team do almost anything they would normally do in Python (pandas / polars / openpyxl) or in the file's own application (Excel, PowerPoint, Word). So libraries are scored on a capability checklist, not just read/write. Each format gets its own research pass.

## Licences and status (Python: verified from PyPI; .NET: from each project's README/page, legal should confirm)
| Library | Licence | Status / notes |
|---|---|---|
| openpyxl 3.1.5 | MIT | last release 2024-06-28 (slow cadence). Reads/writes xlsx/xlsm |
| XlsxWriter 3.2.9 | BSD-2-Clause | write-only, rich features |
| python-calamine 0.8.2 | MIT | released 2026-07-13. Read-only: xlsx, xls, xlsb, ods. pandas >= 2.2 can use it as an engine |
| pandas 3.0.6 | BSD-3 | wraps the engines above |
| xlrd 2.0.2 | BSD | .xls (old format) only |
| pyxlsb 1.0.10 | LGPLv3+ | last release 2022. Avoid (calamine reads xlsb) |
| polars 1.44.2 | MIT | |
| ClosedXML | MIT | xlsx/xlsm only (no .xls), built on Open XML SDK, not thread-safe |
| MiniExcel | Apache 2.0 | streaming xlsx/csv only, basic templates, v2 in preview |
| ExcelDataReader | MIT | read-only streaming: xlsx, xlsb, xls, csv |
| NPOI 2.8.0 | Apache 2.0 + EULA on binary releases since 2.8.0 | xls, xlsx, docx. README says a monthly maintenance fee applies to organisations that generate revenue. A commercial deployment likely counts: needs legal |
| EPPlus 5+ | Polyform Noncommercial | commercial use needs a paid licence (subscription about $329-569 per developer per year, or perpetual from about $809-899) |
Not checked: Sylvan.Data.Excel, Open XML SDK used directly (NuGet API was blocked in the sandbox).

## Measured, 500,000 rows x 10 columns (single run, 2-core sandbox, synthetic data)
| Task | Time | Peak memory |
|---|---|---|
| XlsxWriter write, constant_memory | 31.8 s | 19 MB (30 MB file) |
| openpyxl read, read_only mode | 50.1 s | 86 MB |
| python-calamine read (all rows to Python) | 5.5 s | 609 MB |
| openpyxl read, normal mode | 84.9 s | 2,126 MB |
- ClosedXML's own README (author's numbers, not mine): million-row text workbook loads in 49 s / 801 MB and saves in 23.4 s / 1,880 MB.
- An .xlsx sheet holds at most 1,048,576 rows, so multi-million-row files cannot be xlsx anyway.
- openpyxl read_only: cannot modify; must close the workbook; dimensions may need `reset_dimensions()`. write_only: append rows only, save once, under 10 MB memory per docs. XlsxWriter constant_memory: rows must be written in order, no `add_table()`.

## Capability tests (Python, run in the sandbox)
Built a workbook with XlsxWriter containing: number formats/bold/fill, formulas, conditional formatting, data validation list, freeze panes, autofilter, merged cells, comment, hyperlink, defined name, image, chart, and an Excel Table. Then opened it with openpyxl, changed a cell, saved.
- Everything survived: all of the above present, and the chart kept type, series and references; cell styles, conditional formatting, and validation matched.
- Caveat: this was a simple, library-made workbook. Excel-authored files with pivot tables, slicers, sparklines, form controls, VBA, external links or complex chart formatting were NOT tested. openpyxl docs do not list what it drops.
- Formulas are stored as text with NO calculated value. XlsxWriter files hold cached 0; openpyxl-saved files hold nothing. Readers that do not calculate (pandas, calamine, most database tools) see 0 or None. LibreOffice headless recalculation on a copy gave correct values (11450.75, 2862.6875, 2).
- Pivot tables: openpyxl can preserve and edit existing ones but its docs say client code is not intended to create them. XlsxWriter: docs I fetched did not say (my recollection is it cannot; unverified).
- Not tested: VBA/xlsm (openpyxl `keep_vba`), .xls writing, external data connections, PDF export, slicers.

## Three tiers of Excel capability
1. Libraries (openpyxl, XlsxWriter, pandas, polars): data, formatting, formulas as text, conditional formatting, validation, tables, images, basic charts. Cannot calculate formulas, create pivot tables, run macros, refresh data connections, or render/export.
2. LibreOffice headless: recalculates formulas (tested), converts xls/xlsx, can export PDF. It is an installed application (does the "no off-the-shelf products" rule allow it as a conversion engine?). It rewrites the file, so use it on a copy to read values; fidelity of its output not tested.
3. Excel itself via COM (xlwings / pywin32) on a Windows machine: full parity (pivots, macros, refresh, PDF). Needs Excel installed and licensed where the automation runs. (My recollection, unverified: Microsoft does not support unattended server-side Office automation.)

## Elsa
No Excel support at all (only a MIME mapping). Everything above would be worker or custom-activity work.

## Working recommendation (my reasoning, not decided; Python-only view, see the language verdict below)
Python worker: calamine or pandas to read; openpyxl to edit existing workbooks (round trip held up on common features); XlsxWriter to create big or styled files; compute formula results in Python or recalculate on a copy with LibreOffice/Excel; for pivots either write a pandas summary table or drive Excel.

## Decisions needed from Hope
- Is desktop Excel installed on the machines that would run automation? Is unattended use allowed?
- Is LibreOffice acceptable as a conversion/recalculation engine?
- Which Excel features do current workflows really use (pivots, macros, charts, external links)?

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

How to read the evidence tags: [measured] = run in this sandbox on 2026-09-30 (2 cores, 8 GB, single runs). [tested] = capability tested, no timing. [docs] = read from a project page or README. [reasoning] = my inference.
Test data was regenerated for this pass (not the same files as 2026-09-29), so compare numbers within this table. The Python baselines were re-run and came out 6-30% slower than the earlier numbers above (openpyxl read_only was the biggest gap: 64 s vs 50 s).
.NET limit: NuGet is blocked in the sandbox, so NO third-party .NET Excel library could be run. .NET rows below are [docs] only.

### Speed, 500,000 rows x 10 columns [measured]
| Task | Python | JavaScript | .NET |
|---|---|---|---|
| Read, fastest option | calamine 6.3 s, 633 MB | exceljs streaming reader 20.5 s, 202 MB | not measured |
| Read, low-memory option | openpyxl read_only 64.4 s, 86 MB | (same exceljs streaming run) | not measured |
| Read, whole file in memory | (openpyxl normal mode 84.9 s / 2.1 GB, earlier run) | exceljs load 23.6 s, 2.9 GB; SheetJS (@e965/xlsx fork) 24.8 s, about 2 GB (read + write in one process) | ClosedXML README (author's numbers): 1M rows load 49 s / 801 MB |
| Write, streaming | XlsxWriter constant_memory 33.9 s, 19 MB | exceljs streaming writer 11.5 s, 364 MB (no styles, no shared strings) | ClosedXML README: 1M rows save 23.4 s / 1,880 MB (not comparable) |
So: Python reads fastest (calamine, 3x faster than the best JS option). JavaScript writes fastest (about 3x faster than XlsxWriter) but with a plain, unstyled writer. Whether .NET beats either is unknown.

### Edit an existing, feature-rich workbook [tested]
Built one workbook (formulas, conditional formatting, validation list, freeze panes, autofilter, merged cells, comment, hyperlink, defined names, image, chart, Excel Table), loaded it, changed one cell, saved, then counted the parts in the saved file.
| Feature | openpyxl (Python) | exceljs (JS) | SheetJS community build (JS) |
|---|---|---|---|
| Formulas, freeze panes, autofilter, merged cells, hyperlink, comment, defined names, table, image | all kept | all kept | formulas, autofilter, merged cells, hyperlink, comment, defined names kept; freeze panes, table, image LOST |
| Conditional formatting, validation list | kept | kept (validation range came back split into 2 overlapping rules) | LOST |
| Chart | KEPT | LOST | LOST |
- ClosedXML (.NET) [docs]: its GitHub issue #50 asks for chart support and the maintainer's answer is that it is a big change; issue #869 reports existing charts disappearing after save (versions 0.92 to 0.95.3, fix claimed then reported unresolved). The workaround in the thread is to add charts afterwards with the Open XML SDK. So ClosedXML is not a safe editor for workbooks that contain charts.
- Test file was simple and library-made (same caveat as above). Pivot tables, slicers, VBA were not tested in any language.

### Maintenance and licences [docs, npm/PyPI/README]
- exceljs 4.4.0: MIT, last npm release 2024-12-20. openpyxl 3.1.5: MIT, last release 2024-06-28. Both slow.
- SheetJS: the `xlsx` package on npm is stuck at 0.18.5; the maintainers publish newer builds from their own site (cdn.sheetjs.com), which is blocked from my sandbox, so I could not check it. The community build does not keep most formatting (table above). `@e965/xlsx` 0.20.3 (Apache-2.0) is a community mirror of a newer version.
- write-excel-file 4.1.1 and read-excel-file 9.3.10 (MIT, active 2026): installed, not benchmarked.
- .NET: ClosedXML MIT (not thread-safe), MiniExcel Apache-2.0 (streaming, basic; editing an existing file is limited), Sylvan.Data.Excel MIT (read-only fast reader; its writer only exports flat data, no formatting or charts), ExcelDataReader MIT (read-only). EPPlus and NPOI carry licence risk for a commercial deployment (see table above).

### VERDICT: Python for the whole Excel tool
Why: fastest reading (calamine), the only library in my tests that edited a feature-rich workbook without dropping anything (openpyxl), the richest creator (XlsxWriter), and pandas/polars for the data work in one place. JavaScript wins one race (bulk write of a plain file, about 3x faster) but loses charts on edit; .NET has no measured advantage and ClosedXML cannot create charts.
The 34 s write time for 500,000 rows in Python is the price. If a workflow ever needs very fast plain exports, the fix is inside the Python tool (write CSV, or split), not a second language.
What would change this: a run on a machine that can reach NuGet showing ClosedXML/ExcelDataReader/Sylvan reading 500,000 rows in under about 6 s AND an Open XML SDK route that keeps charts on edit. Until then .NET is unproven, not ruled out.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The Python verdict stands: python-calamine to read, openpyxl to edit, XlsxWriter to create, pandas/polars for data (`BUILD_PROMPT:58`).
- The .NET and JavaScript rows are reference only.
- LibreOffice recalculation is optional and off by default. Desktop Excel via COM is not in the MVP.
