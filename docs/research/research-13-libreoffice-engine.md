# Research 13: LibreOffice as a conversion/recalculation engine (2026-09-29)

## Hope's answers
- Desktop Office can be installed on the machines, but it is unclear whether a SERVICE ACCOUNT would hold a licence.
- LibreOffice is fine if it is "safe".

## Facts
- Licence: MPL-2.0 (from the installed package docs). Sandbox version tested: LibreOffice 24.2.7. Current release scheme/dates: page blocked, NOT verified.
- Security: the advisories page lists 9 CVEs for 2026 (as of 2026-09-29), mostly memory-safety bugs in file-format handlers (WMF, PDF, PPT, CFF fonts, PICT, Calc spreadsheet handling) and one where package URLs in a document could leak INI values and environment variables (CVE-2026-63278). I read the list, not each advisory.
- Macros: by default only run from trusted locations or when signed (LibreOffice's security page).

## Operating rules that follow (my reasoning unless noted)
1. Use it only on files WE generated (recalculate formulas, make PDFs, convert xls to xlsx). Read files we RECEIVED with the libraries (memory-safe languages).
2. Keep secrets out of its environment variables; no network access; macros off; run with a low-privilege account.
3. One profile folder per worker (`-env:UserInstallation=file:///...`) and a timeout around every call (sources: cheatsheet and a Docling issue report silent failures and hangs on corrupt input).
4. Tested here: two simultaneous conversions on the SAME profile both succeeded (could not reproduce the reported collision; small files, timing may matter). Separate profiles also worked.
5. Batching several files in one call is faster than starting it repeatedly (cheatsheet: 5.96 s vs 13.52 s for its test set). `unoserver` 3.7 (MIT, June 2026) keeps LibreOffice running as a server (2 to 4 times throughput claimed) but has NO security on its ports: keep it on localhost/private network only.
6. Pin a supported version and patch on a schedule.

## What was verified using it
- Excel formulas recalculated correctly on a copy (research-05); docx and pptx to PDF rendered correctly (research-10, 11); docx to legacy .doc and back ran without error.
- Not verified: how faithfully it preserves complex Excel-authored files (so read values from its output, do not ship it).

## Desktop Office
Optional. Not verified: Microsoft's position on unattended server-side Office automation (its page returned 403); my recollection is it is unsupported. Service-account licence question is open with the organisation.

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [tested] = done in this sandbox on 2026-09-30; [reasoning] = inference.

LibreOffice is a separate program that any language starts as a child process (`soffice --headless --convert-to ...` with its own profile folder and a timeout), so the language of the caller makes no difference to what it can do or how fast it converts. Everything in this session that needed it (rendering the JavaScript-made .docx, .pptx and .xlsx to PDF to check them) ran the same command from a shell [tested]. A UNO bridge for driving it in-process exists (Python's is the usual one, my recollection, unverified), but nothing here needed it and none was tested.

### VERDICT: language-neutral; call it from whichever worker owns the file tool
In practice that is the Python worker for Excel, Word and PPTX (research-05, 10, 11 verdicts), started as an external process with the operating rules above. The .NET runner itself should not load LibreOffice in-process. Keep it out of the Elsa server process.

## Update 2026-09-30 (later): Hope wants LibreOffice evaluated for office files
Hope's words: if LibreOffice is good, we can test it for office file extensions. The test plan (research-20, section 4b and area LO) therefore treats LibreOffice as a candidate for xlsx/xls, docx/doc, pptx/ppt and ODF files, on four criteria: coverage of the operations checklists (through the command line and the UNO API), a conversion matrix including legacy formats and passwords, round-trip fidelity (which features are lost when LibreOffice re-saves a file), and reliability and speed (20 conversions in a row, corrupt input, leftover processes, parallel runs, 50-file batch, 500,000-row workbook). Nothing has been run yet. Still open with the organisation: LibreOffice is an open-source program, not a library, so the rule "libraries yes, products no" needs an answer, and the licence needs legal confirmation.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The operating rules apply unchanged: generated files only, own profile per worker, timeout, no network, macros off, low-privilege account.
- Read "keep it out of the Elsa server process" as: never in the FastAPI control-plane process, only inside a worker's activity subprocess.
- In the MVP, LibreOffice recalculation is optional and off by default (`BUILD_PROMPT:58`). The "libraries yes, products no" ruling is still open.
