# Research 12: log files (2026-09-29)

Assumption: "log" covers both (a) reading and parsing big log files and (b) writing the automation's own logs. Correct me if only one matters.

## (a) Parsing log files: measured
Test file: 3,036,168 lines, 242 MB, with multi-line stack traces mixed in (about 36,000 continuation lines). Task: count ERROR lines per job.
| Approach | Time | Peak memory |
|---|---|---|
| Python streaming with regex (line by line) | 1.7 s | 8 MB |
| polars (lazy, streaming, regex extract) | 0.6 s | 371 MB |
Both gave identical results. Python streaming handles continuation lines easily and can tail or resume from an offset. Log rotation/tailing (`pygtail` is GPL v2: avoid; `drain3` 0.9.11 MIT for log template mining, last release 2022) was not tested.

## (b) Writing logs
- Python: structlog 26.1.0 (MIT or Apache-2.0), loguru 0.7.3 (MIT, last release 2024-12), stdlib `logging`.
- .NET: Serilog (Apache-2.0), structured logging with rolling file sinks (README).

## Elsa
- Has a `Log` activity (`Elsa.Logging`) and diagnostics modules: `Elsa.Diagnostics.ConsoleLogs`, `StructuredLogs`, `OpenTelemetry` (existence verified by folder listing; not examined).
- Elsa also keeps its own activity execution logs (see research-04 on what gets persisted).

## Verdict (Python-only view from 2026-09-29; superseded by the language verdict below)
Python worker for parsing; Serilog/structlog for the tool's own logs. Decide early where workflow and worker logs go so one job can be traced across Elsa and workers (a correlation id).

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [measured] = run in this sandbox on 2026-09-30 (2 cores, 8 GB, single runs); [docs] = README/npm page; [reasoning] = inference.
.NET limit: NuGet is blocked in the sandbox, so only built-in .NET was run. Serilog is [docs] only.

### (a) Parsing: count ERROR lines per job [measured]
Test file regenerated for this pass: 3,036,168 lines, 190 MB, stack-trace continuation lines mixed in. All runs found the same result: 244,628 ERROR lines across 50 jobs.
| Language | Approach | Time | Peak memory |
|---|---|---|---|
| Python | line loop + compiled regex | 1.43 s | 10 MB |
| Python | polars lazy streaming + regex | 0.44 s | 280 MB |
| .NET | StreamReader.ReadLine + compiled Regex | 0.74 s | 165 MB |
| JavaScript | readline + regex | 1.55 s | 126 MB |
| JavaScript | manual 1 MB chunks + regex | 0.79 s | 109 MB |
polars is fastest; .NET is the fastest plain loop (about 2x Python's); JavaScript's readline is a tie with Python and needs hand-tuning to match .NET. On a file this size every option finishes in under 2 s, so speed does not decide it. What does: multi-line records (stack traces), tailing and resuming from an offset, and analysis after parsing (group, join, export). Those are easiest in Python, and polars/pandas are right there. Tailing and rotation were not tested in any language.

### (b) Writing the automation's own logs [docs, reasoning]
This is platform plumbing, not a file tool. Serilog (.NET, Apache-2.0) fits the runner because Elsa is .NET; workers log with their own library (structlog in Python, pino 10.3.1 or winston 3.19.0 in JavaScript, all MIT/Apache) in one agreed structured format with a correlation id, so a job can be followed across languages. pino and winston were not run.

### VERDICT
- Log PARSING tool: Python (polars for big files, plain streaming for stack traces and tailing).
- The automation's OWN logging: .NET/Serilog in the runner, with every worker (any language) emitting the same structured JSON fields and correlation id. That is a contract, not a language choice.
What would change the parsing verdict: files of many GB with simple filtering only, where a .NET streaming node would be about twice as fast as the Python loop (polars still faster).


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- Parsing becomes the `txt_log` activity (Python, polars or streaming).
- Own logging: Serilog is superseded by structlog JSON logs with rotating files (`BUILD_PROMPT:84`). The contract still applies: every process emits the same JSON fields and correlation id.
