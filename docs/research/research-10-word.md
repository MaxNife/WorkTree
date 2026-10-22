# Research 10: Word (.docx, .doc) (2026-09-29)

## Python (licences from PyPI)
| Library | Licence | Latest | Use |
|---|---|---|---|
| python-docx 1.2.0 | MIT | 2025-06-16 | create/edit .docx |
| docxtpl 0.20.2 | LGPL-2.1-only | 2025-11-13 | fill Word templates (Jinja tags). LGPL: flag for legal |
| docx2python 3.7.1 | MIT | 2026-08-06 | extract text incl. tables, headers |
| mammoth 1.13.0 | BSD-2 | 2026-09-26 | docx to clean HTML |
| docxcompose 2.2.0 | MIT | 2026-06-02 | merge documents |

## Capability tests (python-docx 1.2.0, run in the sandbox)
- Created: title, headings, formatted runs (bold, size), bullet lists, styled table, image, header text, footer text, page break, a TOC field. All worked.
- Edited an existing file: replaced text inside a run and the formatting was kept. Added a comment through the comment API (works in 1.2.0).
- Rendered through LibreOffice to PDF: 2 pages; header, footer, edited text, table and bullets all correct.
- python-docx's own docs page still says headers/footnotes cannot be changed. That is out of date: header and footer text worked in the test. Trust tests over docs.
- GAP: the table of contents was NOT updated. The PDF showed the placeholder text. A TOC needs Word, or a LibreOffice/UNO step to update fields (the UNO step was not tested).
- Legacy .doc: python-docx does not read .doc. LibreOffice converted docx to doc and back without error (exit 0; content of the round trip was not compared).
- docx2python found table text and the header; mammoth produced HTML with `<h1>` and `<table>`.
- Not tested: tracked changes, footnotes, page-number fields, mail merge, complex layout fidelity between Word and LibreOffice.

## .NET (from each project's README)
- Open XML SDK: MIT, Microsoft. Low level (you need to know the file format); README warns ZIP packages on .NET Core and later cannot stream.
- Xceed DocX 5.2.0 (June 2026): free only for NON-commercial use (Xceed Community License), commercial licence needed. Avoid here.
- NPOI (xls, xlsx, docx): Apache 2.0 but README asks a monthly maintenance fee from revenue-generating organisations (see research-05).

## Elsa
Nothing for Word.

## Verdict (Python-only view from 2026-09-29; superseded by the language verdict below)
Python worker: python-docx (+ docx2python, mammoth, docxcompose). Templates: docxtpl if LGPL is accepted, otherwise placeholder replacement written in-house. PDF via LibreOffice on our own generated files. Real Word only for TOC/fields or layout-critical documents (licence question open).

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [tested] = run in this sandbox on 2026-09-30 (no timing needed; these are capability tests, checked by rendering through LibreOffice to PDF and by reading the files back); [docs] = README/npm page; [reasoning] = inference.
.NET limit: NuGet is blocked in the sandbox, so the Open XML SDK could NOT be run. It is [docs] only.

### JavaScript, `docx` 9.8.1 (MIT, updated 2026-09-28) [tested]
- Created from scratch: title, heading, bold/large runs, bullets, table, image, header, footer, page break. All rendered correctly in the PDF (image confirmed present).
- TOC: the table-of-contents field was written but NOT filled in the PDF, the same gap as python-docx. Needs Word (the library can ask Word to update fields on open) or a LibreOffice step.
- Editing an existing .docx: its `patchDocument` replaced `{{client}}` and `{{amount}}` placeholders inside a file made by python-docx and kept the bold 14 pt formatting (the value came back in extra runs with the same formatting).
- Not tested for `docx`: opening an existing document and changing arbitrary paragraphs, tables or comments. [docs/reasoning] It is primarily a generator; placeholder patching is its edit path.
### JavaScript, docxtemplater 3.71.0 (core MIT) + pizzip [tested]
- Filled `{{client}}` and `{{amount}}` in the same template with the run formatting untouched (one run, "Client: ACME Ltd", bold 14 pt). It is the closest thing to docxtpl, but under MIT (docxtpl is LGPL). Not verified: docxtemplater's extra modules (images, tables, HTML) may be paid add-ons; check before relying on them.
### JavaScript, mammoth 1.13.0 (BSD-2) [docs]
mammoth started life as a JavaScript library; the Python package above is a port. docx to clean HTML in both.
### Python (from the earlier tests)
python-docx creates and edits arbitrary content (any paragraph, table, run, header, comment), docx2python extracts text, docxcompose merges documents. There is no JavaScript equivalent for merge or full text extraction in my tests.
### .NET [docs]
Open XML SDK (MIT, low level, Microsoft), Xceed DocX (non-commercial only), NPOI (maintenance fee for revenue-generating organisations). Nothing high level and safely licensed was found; a template-fill or edit helper would have to be written on the Open XML SDK.

### VERDICT: Python for the whole Word tool
Reason: Python can create AND edit arbitrary existing documents, extract text, and merge; JavaScript can create and fill templates but only placeholder-patch existing files; .NET is low-level or licence-risky. The TOC/fields gap is the same in every language and is solved outside them (Word or LibreOffice).
Template filling is the only close spot. docxtemplater (MIT) in JavaScript does what docxtpl (LGPL) does in Python. If legal will not accept LGPL, either write the placeholder replacement in-house in Python (it is a small job) or use docxtemplater in a JavaScript step. Under the "one language per linear tool" rule, prefer the in-house Python version.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- Out of MVP scope (`BUILD_PROMPT:65`). The Python verdict stands for later. Nothing here changes the MVP build.
