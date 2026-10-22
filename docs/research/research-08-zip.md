# Research 08: ZIP and other archives (2026-09-29)

## Python (licences from PyPI)
| Library | Licence | Notes |
|---|---|---|
| stdlib `zipfile` | PSF | reads/writes normal zips. TESTED: cannot open an AES-256 password zip (`NotImplementedError: That compression method is not supported`) |
| pyzipper 0.4.0 (2026-05-14) | MIT | TESTED: wrote and read an AES-256 password-protected zip |
| py7zr 1.1.3 (2026-06-19) | LGPL-2.1-or-later | TESTED: created and extracted a password-protected 7z. LGPL: flag for legal |
- Reading a CSV directly from inside a zip with pandas in chunks works (3M rows, 7.7 s, 514 MB peak).
- Security test (zip-slip): a zip with an entry named `../../escaped.txt` extracted with `zipfile.extractall` was written INSIDE the target folder as `escaped.txt`, not outside it. Python sanitises path traversal. Still worth capping total extracted size and file counts (zip bombs) for downloads: NOT tested here.

## .NET (from each project's README/page)
- System.IO.Compression: built into .NET; password protection not checked.
- SharpZipLib: MIT (relicensed from GPLv2). zip, gzip, tar, bzip2; PKZIP and AES encryption; Zip64.
- SharpCompress: MIT. Reads zip, 7z, RAR, tar, gz, bz2, xz, zstd and more; writes zip, tar, gz, bz2, 7z and more; password support; streams non-seekable inputs; async.

## Elsa
Only `CreateZipArchive` exists (Elsa.IO.Compression): takes byte[]/stream/file path/URL/base64/entries and a compression level. No extract activity found and no password option seen in its inputs.

## Verdict (Python-only view from 2026-09-29; superseded by the language verdict below)
Python worker for extract and password zips (pyzipper; py7zr only if 7z is needed and LGPL is accepted). If a .NET activity is needed, SharpZipLib or SharpCompress (both MIT) cover passwords. Nothing was tested for RAR.

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [measured] = run in this sandbox on 2026-09-30 (2 cores, 8 GB, single runs); [tested] = capability tested; [docs] = README/page; [reasoning] = inference.
.NET limit: NuGet is blocked in the sandbox, so only the built-in System.IO.Compression was run. SharpZipLib and SharpCompress are [docs] only.

### Speed on the 261 MB, 3M-row CSV [measured]
| Task | Python | .NET (built-in) | JavaScript |
|---|---|---|---|
| Write it as a deflate zip (output about 90 MB) | 16.0 s, 12 MB | 15.6 s, 33 MB | archiver 8.0.0: 14.7 s, 135 MB (88.6 MB out) |
| Stream the CSV out of the zip and group-by | pandas chunks 3.5 s, 173 MB | 3.1 s, 165 MB | unzipper 5.1 s, 134 MB; node-stream-zip 6.4 s, 81 MB |
A tie: compression speed is set by the zlib code underneath, not the language.

### Password (AES-256) zips [tested]
| Library | Result |
|---|---|
| Python pyzipper (MIT) | writes and reads AES-256 (earlier test) |
| JavaScript @zip.js/zip.js 2.18.2 (BSD-3) | wrote an AES-256 zip, read it back, and also read the pyzipper-made zip with the password |
| JavaScript adm-zip 0.6.1, unzipper 0.12.5, node-stream-zip 1.16.0 | all FAILED on the AES zip ("Incompatible password parameter", BAD_PASSWORD, "Entry encrypted") |
| .NET built-in ZipArchive | FAILED: `InvalidDataException: The archive entry was compressed using an unsupported compression method` (same wall as Python's stdlib) |
| .NET SharpZipLib / SharpCompress | README says AES/passwords are supported; NOT run [docs] |

### Zip-slip (an entry named `../../escaped.txt`) [tested]
- Python zipfile: sanitised, file landed inside the target folder (earlier test).
- .NET `ZipFile.ExtractToDirectory`: threw `IOException: Extracting Zip entry would have resulted in a file outside the specified destination directory`. Safe by default.
- JavaScript: node-stream-zip threw "Malicious entry"; adm-zip and unzipper wrote nothing outside the folder (adm-zip put it inside). Old versions of these libraries had zip-slip bugs, so keep versions current and still cap extracted size and file counts. Zip bombs were NOT tested in any language.

### Other formats [docs]
- 7z: Python py7zr (LGPL, tested earlier) vs .NET SharpCompress (MIT; README says it writes 7z and reads RAR). JavaScript: no 7z library tested (would mean wrapping an external 7z binary).
- Licence angle: .NET SharpCompress/SharpZipLib are both MIT; Python's 7z route needs the LGPL library approved.

### VERDICT: Python for the whole ZIP tool (lean; one licence condition)
Reason: zip creation and reading are a tie in speed; Python is the one where AES-256 and 7z are already proven end to end (pyzipper MIT, py7zr LGPL), and it fits the pandas pipeline (read a CSV straight out of the zip).
The flip condition: if legal refuses LGPL (py7zr) AND 7z or RAR is really needed, the ZIP tool should become .NET on SharpCompress (MIT) instead, after a test of its AES and 7z claims. JavaScript is last: only one of four zip libraries handled passwords.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The Python verdict stands: pyzipper (MIT) for AES-256 zips, with zip-slip protection and size/count caps (`BUILD_PROMPT:58`). Zip bombs must now be tested (`docs/BUILD_CHECKPOINTS.md` CP-23).
- The flip condition to .NET SharpCompress is no longer available. If legal refuses LGPL (py7zr) and 7z/RAR becomes necessary, record it in `KNOWN_GAPS.md`. The MVP spec does not require 7z.
