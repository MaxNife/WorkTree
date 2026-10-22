# Research 03: Oracle from Elsa, .NET and Python (2026-09-29)

Context: target DB is mostly Oracle. Graph app registration, read/write rights and RBAC are already set up by the security team (so Graph is an access-solved, build-pending item). Playwright use is approved (hosting design still open). Items marked (my reasoning) are inferences, not verified.

## Elsa side (verified in code)
- Elsa's SQL activities (`SqlQuery`, `SqlCommand`, `SqlSingleValue`) have providers for MySql, PostgreSql, SqlServer, Sqlite only. No Oracle.
- Adding Oracle is small: a client class inherits `BaseSqlClient` and only supplies `CreateConnection()` and `CreateCommand()` (the PostgreSQL one is about 3 lines), then is registered with `client.Register<OracleClient>("Oracle")` in `Program.cs`. No fork.
- Oracle needs `:` as the parameter marker (base default is `@`); the base class lets a subclass override it. (my reasoning) ODP.NET binds by position unless `BindByName = true`, so set that. Untested.
- Limits of the SQL activities for ANY database: a new connection per activity call; one statement per call; no transaction spanning several activities; no bulk load; `SqlQuery` reads the whole result into a `DataSet` in memory (and it is not saved with workflow state). So do not pull big extracts through it.
- (my reasoning) PL/SQL: an anonymous block (`BEGIN proc(:p0); END;`) should run through `SqlCommand` as plain text; the activity has no stored-procedure command type. Untested.
- Elsa's own workflow storage has an Oracle option: `Elsa.Persistence.EFCore.Oracle` (Oracle.EntityFrameworkCore 9.23 / 10.23 packages, with migrations). BUT the newer `Elsa.Persistence.VNext` modules list SqlServer, PostgreSql, Sqlite, MongoDb, and no Oracle. Which persistence is the future, and which Oracle DB versions the EF provider supports, are unchecked.

## .NET driver
- `Oracle.ManagedDataAccess.Core` on NuGet: latest 23.26.301 (2026-09-08), described as a single 100% managed DLL (so no Oracle Client install; the page did not state this outright), targets .NET 8 / netstandard2.1.
- Supported Oracle DB versions: the NuGet page does not say. Oracle says the client version need not match the DB version. Must be verified against the actual Oracle versions.
- Licence: free to download, but the licence text was not visible in what I read. Legal/compliance should read it.

## Python driver
- `python-oracledb` thin mode: no Oracle Client libraries, connects to Oracle DB 12.1 or later. Thick mode needs Oracle Instant Client and supports 11.2+. Tested with Python 3.10 to 3.15 against DB 19, 21, 26.

## Loading data fast: options
1. Batch inserts (array binding in .NET via `ArrayBindCount`; `executemany()` in Python). Fewer network round trips than row-by-row; per-row errors reported (Python `batcherrors=True`, ODP.NET returns an error per failing row). Python docs: use `setinputsizes()` and `batch_size`; a 2 GB buffer limit gives error DPI-1015 if a batch is too big.
2. `OracleBulkCopy` in .NET (managed and Core supported): direct path load, faster than INSERTs, but restrictions: no global indexes on the target table (for single-partition loads), foreign-key constraints get disabled, insert triggers are disabled and NOT re-applied to the loaded rows, database column defaults are not applied (NULLs unless configured), no overwrites. Python docs also mention direct path loads with schema restrictions.
- (my reasoning) Default to batch inserts (safe, row-level errors). Consider direct path only for staging tables without triggers/FKs, then move rows to the real table with a MERGE or INSERT..SELECT.

## Open questions
- Which Oracle version(s) does the target environment run (11g / 12c / 19c / newer)? Decides thin mode vs Instant Client, and driver choice.
- How do connections authenticate (username/password, wallet, TNS names, TLS, Kerberos)?
- Typical load patterns and sizes: append, truncate+insert, or upsert; rows per file.
- Where the Oracle load should live: Elsa SQL activity (small/parameterised, PL/SQL calls) vs a worker (file loads via executemany or array binding).

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [docs] = official page read on 2026-09-30; [reasoning] = inference.
Limits: there is no Oracle database in the sandbox, so NO load-speed number exists for any language. NuGet is blocked, so ODP.NET could not be installed either. Everything below is [docs] or [reasoning].

### The three drivers (all three are published by Oracle)
| | .NET | Python | JavaScript |
|---|---|---|---|
| Driver | `Oracle.ManagedDataAccess.Core` 23.26.301 (2026-09-08), 100% managed | `python-oracledb` (thin mode default) | `oracledb` (node-oracledb) 7.0.1 (2026-07-15), thin mode default |
| Licence | not visible on the NuGet page (again): legal must read it | not checked (I believe Apache-2.0 / UPL, unverified) | (Apache-2.0 OR UPL-1.0) per npm |
| Needs Oracle Client install | no | not in thin mode | not in thin mode |
| DB versions in thin mode | not stated on the page | 12.1 or later | "Release 12.1 and later" |
| Array insert with per-row errors | `ArrayBindCount` | `executemany(batcherrors=True)` | `executeMany()` with batch errors ("Yes" in the docs' feature table) |
| Direct path load | `OracleBulkCopy` (restrictions in the section above) | `direct_path_load()` (thin) | added in node-oracledb 7.0.0, thin mode only (release notes: "Added support for Direct Path Loads") |
| PL/SQL calls | yes | yes | yes ("For scalar types and collection types using array interface") |
| TLS / wallet connections | yes (managed driver) | yes | one-way TLS and mutual TLS supported |
Only the JavaScript column was read from its own docs in this pass. The .NET and Python cells come from the notes above or from general knowledge and were not re-read.
Gaps the node-oracledb docs list for its THIN mode: no native network encryption, no Kerberos/Radius/PKI authentication, no LDAP connections, no external authentication, no sqlnet.ora (a few values through the connect string), no CQN, no SODA, no session tagging. If the organisation uses any of these (unknown), JavaScript needs thick mode (Instant Client). I did not re-check the equivalent list for python-oracledb or the .NET driver in this pass.

### What decides it
- Feature-wise it is close to a three-way tie: all three offer array inserts with row-level errors, direct path load, PL/SQL and TLS. [docs]
- Speed: a bulk load is bound by the database, the network and the batch size much more than by the client language [reasoning]. NOT measured. The benchmark to run once a non-production Oracle is available: load the same 3M-row, 10-column file with (a) array insert and (b) direct path in each language, into a staging table.
- Fit: Elsa's SQL activities are .NET and Oracle needs a small `ISqlClient` extension anyway (see above). With ODP.NET the query/command/PL/SQL activities live in the runner, get Elsa's retry hooks, and need no extra runtime.

### VERDICT: .NET for the Oracle tool (lean, bulk-load speed unmeasured)
Reason: same runtime as the Elsa activities (queries, PL/SQL calls, small loads), Oracle's flagship driver, and a tied feature set, so nothing pushes it elsewhere. Python is a close second (same features, and it can stream batches from a polars/pandas pipeline without a language hop); JavaScript is last (thin mode has the documented gaps above and offers no advantage).
Flip condition: if the benchmark above shows Python's `executemany` or `direct_path_load` clearly beating ODP.NET on the real target tables, move only the BULK-LOAD operation to a Python worker and keep queries and PL/SQL in .NET. Under Hope's rule this would split the Oracle tool in two, so it should take a large margin to justify.
Also still open from the notes above: the target Oracle version, how connections authenticate, and the ODP.NET licence text.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- "Elsa side" no longer applies: there is no `ISqlClient`. Our DB interface has a SQLite implementation for tests.
- "Python driver" and the loading options apply: python-oracledb thin mode; `executemany(batcherrors=True)` with `setinputsizes()` and `batch_size`; watch DPI-1015 (2 GB buffer); `direct_path_load()` only for staging tables. The default pattern is chunked `executemany` into staging, then MERGE (`BUILD_PROMPT:56`).
- Language verdict superseded: Oracle is Python. The ODP.NET licence question is no longer needed. The python-oracledb licence still needs confirming for `LICENSES.md`.
- Open questions (version, auth method, load patterns, triggers/FKs) remain open (`docs/SYSTEM_DESIGN.md` §13).
