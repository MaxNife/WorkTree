# Research 07: TXT / plain text (2026-09-29)

## Python
- Streaming line iteration (stdlib): processed a 242 MB, 3M-line text file in 1.7 s using 8 MB memory (see research-12 for the log test).
- Fixed-width files: `pandas.read_fwf` with column positions worked; use `dtype=str` to keep leading zeros (tested: account numbers and amounts like `000120050` stayed intact).
- Encoding: `charset-normalizer` 3.5.1 (MIT) and `chardet` 7.6.0 (0BSD) exist for detection. Detection is a guess (tested: a cp1252 file was reported as cp1250). Prefer a per-source declared encoding, with detection as fallback.
- polars/DuckDB can also read text files as rows and use regex functions (used in research-12).

## .NET
- Reading/writing text streams is built into .NET. ExcelDataReader's README notes that on .NET Core / .NET 5+ legacy code pages need the CodePages encoding provider registered (same applies to legacy text encodings, my reasoning).
- FileHelpers (fixed-width): not checked.

## Elsa
- `OpenFile` and `SaveFile` (storage module) read and write bytes/streams/strings through one configured storage location. No text parsing, encoding or fixed-width activities.

## Verdict (Python-only view from 2026-09-29; superseded by the language verdict below)
Python worker. Store the source encoding and layout (delimiters, column positions) as per-source settings.

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [measured] = run in this sandbox on 2026-09-30 (2 cores, 8 GB, single runs); [tested] = capability tested; [docs] = README/page; [reasoning] = inference.
.NET limit: NuGet is blocked in the sandbox, so only the built-in .NET 8 libraries were run (which is all plain-text streaming needs). FileHelpers was not run.

### Streaming a big text file line by line, regex on each line [measured]
Test file: 3,036,168 lines, 190 MB (regenerated; same task as research-12: count ERROR lines per job; every run found the same 244,628 errors in 50 jobs).
| Language | Approach | Time | Peak memory |
|---|---|---|---|
| Python | for-line loop + compiled regex | 1.43 s | 10 MB |
| Python | polars lazy streaming + regex extract | 0.44 s | 280 MB |
| .NET | StreamReader.ReadLine + compiled Regex | 0.74 s | 165 MB |
| JavaScript | readline + regex | 1.55 s | 126 MB |
| JavaScript | manual 1 MB chunk splitting + regex | 0.79 s | 109 MB |
So .NET is about 2x faster than plain Python at raw line-by-line work, JavaScript is a tie with Python unless hand-optimised, and polars beats all of them. Python uses far less memory in the plain loop (10 MB vs 100-165 MB for the managed runtimes, which is normal garbage-collector headroom). All are sub-2-second on 190 MB, so speed does not separate them.

### Capability side
- Fixed-width with leading zeros kept: `pandas.read_fwf(dtype=str)` [tested earlier, Python only].
- Encoding: Python has charset-normalizer/chardet (detection is a guess). JavaScript has iconv-lite 0.7.3 (MIT) for conversion and jschardet 4.0.0 (0BSD) for detection; both installed, not exercised. .NET needs the CodePages provider for legacy encodings [docs via ExcelDataReader README, reasoning for text].
- Regex: all three are fine; .NET compiled regex was fastest in the loop above.

### VERDICT: Python for the whole TXT tool (narrow call)
Reason: the tool is about doing "almost anything" with text files (fixed-width layouts, encodings, messy delimiters, then handing rows to pandas/polars), and only Python has those pieces tested end to end. .NET is the fastest at a raw line loop (0.74 s vs 1.43 s), but the gap is under a second on 190 MB, so it does not justify a second language for this tool.
What would change this: if the team finds TXT jobs that are pure line filtering on files of many GB, a .NET streaming node would be about twice as fast as the Python loop (polars would still beat both).


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The Python verdict stands unchanged: the `txt_log` activity, `read_fwf(dtype=str)`, declared encodings with detection only as a fallback.
