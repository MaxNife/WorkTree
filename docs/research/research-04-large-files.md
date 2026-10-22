# Research 04: files with millions of rows (2026-09-29)

Answers two open questions from research-03: the target Oracle is "newer" (exact version not stated; treated as 19c or later), and files range from thousands to a few million rows.

## Consequences of "newer Oracle"
- python-oracledb thin mode (no Oracle Client install) needs Oracle 12.1+, so it should be fine. The .NET managed driver also needs no client install.
- Exact version still worth confirming, since thin-mode direct path and driver support are version-dependent.

## Measurement (Python analogue, not .NET)
Test file: 3,000,000 rows x 10 text columns, 274 MB CSV, generated locally. Machine: 2 cores, 8 GB RAM.
| Approach | Peak memory | Time |
|---|---|---|
| Read whole file into one string, build a list of dictionaries (same shape as Elsa `ReadCsv`) | 3,439 MB | 10.7 s |
| Stream in chunks of 100,000 rows (pandas `chunksize`) | 168 MB | 6.5 s |
Caveats: this is Python, not .NET (memory per row will differ, same order of magnitude); no Oracle was involved, so NO load-speed numbers exist yet.

## Elsa `ReadCsv` (verified in code)
- Reads the whole input into one string (`ReadToEndAsync`), then parses every row into a `List<object>` of dictionaries. Fine for thousands of rows, not for millions.
- Its `Records` output is not marked non-serializable (unlike `SqlQuery`'s `DataSet`, which is). Elsa maps each activity's inputs/outputs into a persisted activity execution record (`DefaultActivityExecutionMapper`), filtered by a per-workflow/per-activity include/exclude log-persistence setting (`LogPersistenceMode`: Inherit, Include, Exclude).
- NOT confirmed: the default for a root workflow, so unknown whether a million-row result would be stored in the execution log by default. Needs a test before trusting.

## Design rule that follows
Elsa passes file paths and small metadata between steps; a worker streams the file in chunks and writes to Oracle. This also covers thousand-row files, so one path for all sizes.

## Loading into Oracle at this size
- Python worker: `cursor.executemany(..., batch_size=N)` in chunks, into a staging table, then MERGE / INSERT..SELECT into the real table (my reasoning).
- `Connection.direct_path_load()` (python-oracledb, thin mode only): takes lists or DataFrames, commits implicitly, cannot take LOB objects. Docs say it may not be faster than `executemany` for smaller sets but can reduce database load and redo. Restrictions on indexes/constraints/triggers are only referenced to Oracle's own docs (not read).
- .NET alternatives: array binding (`ArrayBindCount`), or `OracleBulkCopy` (direct path; disables foreign keys and insert triggers, no column defaults; see research-03).
- To decide by measurement: benchmark executemany vs direct path on a test Oracle instance (none available in the research sandbox).

## Open
- Exact Oracle version; access to a non-production Oracle to benchmark.
- Whether the target tables have triggers, FKs, or global indexes (affects direct path).
- Test what Elsa persists by default for a large `ReadCsv` output.

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [measured] = run in this sandbox on 2026-09-30 (2 cores, 8 GB, single runs); [reasoning] = inference.
This closes the caveat above ("Python, not .NET"). Test file regenerated for this pass: 3,000,000 rows x 10 text columns, 261 MB CSV.
.NET limit: NuGet is blocked, so CsvHelper (what Elsa's `ReadCsv` really uses) could not be run. The .NET rows use built-in code with the same SHAPE as `ReadCsv`: read the whole file into one string, then build a list of dictionaries.

### Whole file into a list of dictionaries (the `ReadCsv` pattern) [measured]
| Language | Time | Peak memory |
|---|---|---|
| .NET (built-in string + Dictionary<string,object>) | 10.8 s | 3,904 MB (3,081 MB of it live managed data) |
| Python (`csv.DictReader` into a list) | 10.6 s | 2,697 MB |
| JavaScript (whole file string, split, object per row) | 5.8 s | 1,674 MB |
Same result in all three (3,000,000 rows). The .NET figure is a lower bound for the real activity, since CsvHelper adds its own overhead on top and Elsa also holds the whole input string while it parses. So loading a 3M-row file that way costs about 4 GB in .NET, on a server that is also running every other workflow. That confirms the design rule above with a .NET number: pass file paths, never the rows.

### Streaming instead (group-by on the same file) [measured]
| Language | Approach | Time | Peak memory |
|---|---|---|---|
| Python | pandas chunks | 2.09 s | 177 MB |
| .NET | StreamReader, line by line | 1.3-1.6 s | 163 MB |
| JavaScript | papaparse streaming | 3.26 s | 82 MB |
Memory stays flat at 80-180 MB in every language. The language does not decide whether a large file works; streaming does.

### VERDICT
Language-neutral for the streaming rule: whichever language a file tool uses must stream, and none of them should hand rows to Elsa. The engine choice for the big-file tools follows the per-format verdicts (CSV: Python with polars/DuckDB, research-06; Excel: Python, research-05). Loading into Oracle: .NET (lean, unmeasured), research-03.
Consequence for Elsa's own `ReadCsv`: do not use it for the millions-of-rows case, in any language plan.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- All measurements and the streaming rule apply unchanged: stream in chunks, pass file paths, never rows. The MVP budget is peak worker memory under 500 MB on the 1M-row scenario (`BUILD_PROMPT:108`).
- Elsa `ReadCsv` and the .NET Oracle alternatives no longer apply.
- The Elsa `LogPersistenceMode` idea becomes our per-workflow/per-step persistence setting (`BUILD_PROMPT:139-166`).
