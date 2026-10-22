# Elsa feasibility: two test projects

Checked against the real code on 2026-09-29: elsa-core `8fadf47`, elsa-extensions `212dc55` (both `main`, NOT a release). Nothing was built or run, this is a code read only.

## Test projects
1. Read an Excel file -> compute/format the Excel/CSV -> deliver to a network share or via Graph API
2. ETL: download files from a portal -> format -> load to a DB table

## What exists (verified in code)
| Need | Status | Evidence |
|---|---|---|
| Read CSV | EXISTS | `Elsa.Data.Csv` `ReadCsv` (CsvHelper) -> list of dictionaries |
| Read Excel | MISSING | no Excel library anywhere in either repo; only a MIME mapping for .xls/.xlsx |
| HTTP download | EXISTS | `DownloadHttpFile` (GET/POST/PUT, headers, Authorization, bytes/stream out) |
| Save/copy file | PARTIAL | `SaveFile`/`OpenFile` use ONE globally configured FluentStorage blob store (default: a local directory) |
| Graph API | MISSING | no Graph package/activity. `SendEmail` is SMTP via MailKit |
| SFTP | MISSING | none |
| Playwright | MISSING | no activity (only an unrelated Studio test project) |
| SQL | EXISTS | `SqlQuery`, `SqlCommand`, `SqlSingleValue`; parameterised; providers: MySql, PostgreSql, SqlServer, Sqlite |
| Oracle | MISSING | no `Elsa.Sql.Oracle`. `ISqlClient` is small (3 execute methods + parameter marker settings) so a provider is an extension, not a fork |
| Bulk insert | MISSING | one statement per activity call |
| Run Python | EXISTS, with limits | `RunPython` uses pythonnet inside the Elsa server process. Disabled unless `PythonOptions.AllowHostCodeExecution = true`. The code itself says it is not a sandbox |
| Run C# | EXISTS, same gating | `RunCSharp` (Roslyn), `CSharpOptions.AllowHostCodeExecution` |
| Run JS | EXISTS | `RunJavaScript` (not examined in detail) |
| AI | EXISTS (not examined) | `Elsa.Agents.*`, `Elsa.AI.*` modules |

## Design points that came out of the code
- `SqlQuery` returns a `DataSet` with `IsSerializable = false`, and `DownloadHttpFile` outputs are also non-serializable. Big data should not travel through workflow variables. Pass file paths / references between steps, not the data.
- `RunPython` is fine for tiny glue, but pandas ETL should go to an isolated Python worker (matches the original plan).
- Every gap above is an extension point (custom activity, DI override, or new `ISqlClient`). No fork needed so far.

## Answers from Hope (2026-09-29)
- Portal login varies per portal, and all three types occur (API token, plain login form, browser login with MFA). So browser automation (Playwright) is a requirement, not optional, and auth must be handled per portal.
- Target DB is mostly Oracle. Elsa has no Oracle SQL client, so this is a required extension.
- Status: research phase only. Nothing is being built or planned yet.

## Not yet checked
- Elsa Studio (designer) behaviour
- Retries / scheduling (`Elsa.Resilience`, `Elsa.Scheduling` exist as folders, not read)
- Whether a released version matches `main`
- End-to-end registration of a custom activity (pattern seen in the code, not run)


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The table is evidence of what Elsa lacks. In the Python build each need maps to an activity:
  - Read Excel → `excel`; Read CSV → `csv`.
  - HTTP download → `download_file` / `http_request`.
  - Save/copy file → run workspace + `unc_archive`.
  - Graph → `email` / `graph_read_mail`; SFTP → `sftp`; Playwright → `playwright_robot`.
  - SQL/Oracle → DB interface + `oracle_query` / `oracle_execute`; bulk insert → `oracle_bulk_load`.
  - Run Python → `run_python` (separate process, not in-process).
  - Run C#/JS → not in the MVP (`legacy_robot_wrapper` can run any executable).
  - AI → `ai_extract`.
- The design point "do not pass big data through workflow variables; pass file references" still applies unchanged.
