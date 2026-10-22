# Research 06: CSV (2026-09-29)

Requirement (corrected by Hope, 2026-09-30): the CSV tool must be able to do anything you can do with a CSV file. It is NOT limited to what pandas/polars can do. The first version of the language verdict below measured against pandas/polars parity, which was the wrong yardstick; it has been redone.

## Python (licences verified on PyPI)
- pandas 3.0.6 (BSD-3), polars 1.44.2 (MIT), DuckDB 1.5.6 (MIT), pyarrow 25.0.1 (Apache-2.0), stdlib `csv`.
- Measured on the 3,000,000-row, 10-column, 274 MB test file: group-by total by branch
  - polars lazy + streaming: 0.4 s, 367 MB peak
  - DuckDB (`read_csv` + SQL): 0.6 s, 185 MB peak
  - pandas chunked (500k rows/chunk, 2 columns): 1.8 s, 112 MB peak
  - All three returned identical sums and counts.
- Reading a CSV inside a zip with pandas in chunks: 3M rows in 7.7 s, 514 MB peak (zip was 84 MB).
- Earlier finding (research-04): reading everything into a list of row-dictionaries took 3.4 GB and 10.7 s for the same file.

## Messy-file tests (all run in the sandbox)
- UTF-8 with BOM + quoted commas + embedded newlines + doubled quotes: pandas parsed correctly with `encoding="utf-8-sig"`.
- Ragged rows (wrong number of fields): pandas raises an error by default; `on_bad_lines="skip"` dropped the bad rows (kept 3 of 4); polars `truncate_ragged_lines=True` kept 4 rows.
- cp1252 file (accents): utf-8 decoding fails as expected; `charset-normalizer` guessed cp1250 (accents came out right on this sample, but it is a guess, since cp1250 and cp1252 differ). Better to declare each source's encoding and use detection only as a fallback.

## .NET
- CsvHelper: dual licence MS-PL / Apache-2.0 (README); what Elsa's `ReadCsv` uses. Active.
- Sylvan.Data.Csv: README page returned 404, NOT verified.
- Nothing in .NET matches polars/DuckDB-style analysis out of the box (not researched: Microsoft.Data.Analysis, DuckDB.NET).

## Elsa
`ReadCsv` (CsvHelper) reads the whole input into one string and builds a list of dictionaries: fine for thousands of rows, not millions (details in research-04). No CSV writer activity found; `SaveFile` can write bytes/strings.

## Verdict (Python-only view from 2026-09-29; superseded by the language verdict below)
Python worker for all CSV work; polars or DuckDB for big files and transformations, pandas for familiarity. Parity with pandas/polars only exists on the Python side.

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [measured] = run in this sandbox on 2026-09-30 (2 cores, 8 GB, single runs); [tested] = capability tested; [docs] = README/page; [reasoning] = inference.
Test file regenerated for this pass: 3,000,000 rows x 10 text columns, 261 MB (the earlier file was 274 MB), so compare numbers inside this table. Python baselines were re-run and landed 15-45% slower than the numbers above (different machine load, single runs).
.NET limit: NuGet is blocked in the sandbox, so CsvHelper, Sylvan and DuckDB.NET could NOT be run. The only .NET numbers are for the built-in library with hand-written parsing.

### Group-by total by branch on the 3M-row file [measured]
| Language | Approach | Time | Peak memory |
|---|---|---|---|
| Python | polars lazy + streaming | 0.56 s | 342 MB |
| Python | DuckDB read_csv + SQL | 0.86 s | 126 MB |
| Python | pandas chunked (500k rows, 2 columns) | 2.09 s | 177 MB |
| JavaScript | nodejs-polars 0.26.1 (lazy scan) | 0.63 s | 435 MB |
| JavaScript | DuckDB (@duckdb/node-api) | 0.89 s | 223 MB |
| JavaScript | papaparse 5.7.0 streaming, row loop | 3.26 s | 82 MB |
| JavaScript | csv-parse 7.0.3 streaming, row loop | 12.56 s | 70 MB |
| .NET (built-in only) | StreamReader + `Split(',')` per line, NO quote handling, no library | 1.57 s | 163 MB |
| .NET (built-in only) | same but scanning the line span by hand | 1.26 s | 163 MB |
All produced identical results (60 branches, sum 149,950,166,252.68, 3,000,000 rows).
What this says:
- Python and JavaScript reach the same speed when they use the same engine (polars / DuckDB are native code, not Python or JS). The language is only a thin wrapper.
- Pure-JS parsers are 5 to 20 times slower than the native engines.
- The .NET rows are a floor, not a verdict: they skip quoted fields, encodings and bad rows, which is exactly what CsvHelper adds. A hand-written parser is faster than pandas here, slower than polars/DuckDB. Whether CsvHelper or Sylvan.Data.Csv beats these numbers: not measured. DuckDB.NET (MIT, bundles the native engine, per its GitHub page [docs]) would give .NET the same engine as Python; not tested.

### Messy-file and everyday CSV operations, JavaScript [tested 2026-09-30]
Same cases as the Python tests above, run in JavaScript (BOM + quoted commas + embedded newlines + doubled quotes; ragged rows; cp1252 accents; semicolon delimiter; writing with quoting):
| Case | Result in JavaScript |
|---|---|
| BOM, quoted comma, embedded newline, doubled quotes | correct in papaparse (BOM stripped, 3 rows, values exact), csv-parse (with `bom: true`), nodejs-polars and DuckDB |
| Ragged rows (one row too long, one too short) | papaparse keeps 4 rows and reports `TooManyFields` / `TooFewFields`; csv-parse errors by default and keeps 4 rows with `relax_column_count`; nodejs-polars kept 4 rows on defaults; DuckDB needs `null_padding=true, ignore_errors=true` (defaults misread the file as one column) |
| cp1252 accents | iconv-lite 0.7.3 decoded correctly (Café, Zoë); decoding as UTF-8 by mistake gives replacement characters, same as Python; DuckDB reads it with `encoding='latin-1'` |
| Semicolon delimiter | papaparse auto-detected `;`; DuckDB sniffed it. Decimal commas stay text (`1,5`), as in Python |
| Write with quoting, read back | papaparse `unparse` quoted commas, quotes and newlines and the file round-tripped identically |
So every case the Python tests covered also works in JavaScript. Not tested in JavaScript: dtype control, joins, pivots, window functions, Parquet output (DuckDB and polars have them in both languages).
Not tested in .NET: NuGet is blocked, so CsvHelper and Sylvan could not be run. CsvHelper is what Elsa's `ReadCsv` uses and its README describes it as an active, full CSV library [docs]. Its behaviour on the cases above is unknown to me.

### What decides it [reasoning]
- Capability does NOT separate Python from JavaScript. Both handle the everyday and messy cases, and both can use the same native engines (polars, DuckDB) for big files. .NET is unproven, not weaker.
- Speed does not separate them either: native engine 0.6-0.9 s in both. Where a language's own parser is used, Python's pandas (2.1 s) beat JavaScript's papaparse (3.3 s) and csv-parse (12.6 s); a hand-written .NET loop (1.3-1.6 s) beat pandas but skips the quoting and encoding work a real library does.
- What remains are tiebreakers, not proof: (1) Python's polars is 1.x and pandas is long established, while nodejs-polars is pre-1.0 (0.26.1, 2026-09-14) and its API coverage vs Python polars was not compared; (2) the team already works in Python, which matters for maintaining the tool (SUPERSEDED 2026-09-30: the team is Python AND .NET developers, so this tiebreak is now neutral); (3) the CSV tool sits next to the Excel tool, which is Python.

### VERDICT: Python for the whole CSV tool, LOW confidence (a tiebreak, not a clear win)
Reason: nothing tested shows Python or JavaScript doing more or running faster; Python wins on library maturity and team fit only. The engines that do the heavy work (polars, DuckDB) are the same in both.
.NET is the open contender: CsvHelper (what Elsa uses) and DuckDB.NET (MIT, bundles the native DuckDB engine per its GitHub page [docs]) could match Python. The test that would settle it: on a machine with NuGet access, run the same 3M-row group-by, the messy cases above and a quoted write through CsvHelper, Sylvan.Data.Csv and DuckDB.NET. If a .NET library handles all of it at polars/DuckDB speed, the CSV tool could move to .NET without loss, and that would save a language hop for CSV-to-Oracle loads.
Do not use Elsa's own `ReadCsv` for big files in any plan (research-04).

### Update 2026-09-30 (later)
Hope confirmed the team is Python and .NET developers and nobody writes JavaScript. Two of the three tiebreakers for Python (team fit, and sitting next to the Excel tool) no longer decide anything, so CSV is open between Python and .NET, with JavaScript dropped. Confidence in "Python" is lower than stated above until CsvHelper, Sylvan.Data.Csv and DuckDB.NET are measured (test plan area CSV). The requirement is also confirmed as "anything you can do with a CSV file"; the test plan has a CSV operations checklist for it.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The open choice between Python and .NET is closed: CSV is Python (polars, DuckDB, pandas). The .NET re-benchmark is not needed for the MVP.
- The messy-file findings (BOM, ragged rows, encodings declared per source) apply and must be covered by `csv` tests.
