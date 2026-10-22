# Research 11: PowerPoint (.pptx) (2026-09-29)

## Python
- python-pptx 1.0.2 (MIT). Last release 2024-08-07, so slow-moving.

## Capability tests (run in the sandbox)
- Created a deck from the default template: title slide, bullet slide, a slide with a native column chart (3 categories), a table, an image, and speaker notes. All worked.
- Rendered through LibreOffice to PDF and viewed the chart slide: chart, table and image all drew correctly.
- Edited an existing deck: changed text in a run (formatting kept). Deleting a slide has no public API; it worked through an XML workaround (dropping the slide relationship and id): 3 slides became 2, and the result still rendered.
- python-pptx's docs page I fetched did not list its limits. NOT tested: animations, transitions, SmartArt, slide masters/layout editing, embedded video, reordering slides (also an XML workaround, my recollection). Anything needing these needs PowerPoint itself.

## .NET (from each project's README)
- Open XML SDK: MIT, low level.
- ShapeCrawler 0.80.0: MIT. Read/create/modify pptx: text, tables, images, charts, slide management. Pre-1.0, smaller community.
- NPOI: README lists xls, xlsx, docx only (no pptx).

## Elsa
Nothing for PowerPoint.

## Verdict (Python-only view from 2026-09-29; superseded by the language verdict below)
Python worker with python-pptx for data-driven decks (reports from templates), LibreOffice for PDF/thumbnails of generated decks. For animations, SmartArt or pixel-exact fidelity, PowerPoint itself (licence question open). Consider keeping a company template deck and filling it.

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [tested] = run in this sandbox on 2026-09-30, checked by rendering through LibreOffice and reading the result back with python-pptx; [docs] = README/npm page; [reasoning] = inference.
.NET limit: NuGet is blocked in the sandbox, so ShapeCrawler and the Open XML SDK could NOT be run. They are [docs] only.

### JavaScript: two libraries, two jobs
- pptxgenjs 4.0.1 (MIT, last release 2025-06-26) creates new decks [tested]: title slide with speaker notes, bullet slide, and a slide with a native bar chart, a table and an image. All three shapes were present when read back, and the LibreOffice render showed the chart, table and image correctly. It does not open existing files (by design; [docs]).
- pptx-automizer 0.9.4 (MIT, updated 2026-09-28, pre-1.0) edits from existing decks [tested]: loaded a python-pptx deck as the root, kept only slides 3 and 1 (dropped slide 2, reordered), and replaced a title's text via `modifyElement('Title 1', [modify.setText(...)])`. Both edits worked without XML workarounds. Not tested: chart data modifiers, images, animations.
### Python: python-pptx (earlier tests)
One library both creates and edits; every shape is reachable. Slide delete and reorder need an XML workaround (worked). Last release 2024-08, slower moving than the JavaScript pair.
### .NET [docs]
ShapeCrawler 0.80.0 (MIT) covers text, tables, images, charts and slide management but is pre-1.0 with a small community; Open XML SDK is low level. Not run.

### VERDICT: Python for the whole PowerPoint tool (close call with JavaScript)
Reason: one library covers create and edit, and it sits with the Excel and Word tools in the same pandas-based worker. JavaScript is genuinely competitive: pptx-automizer edited and reordered slides more cleanly than python-pptx (no XML workaround) and is actively maintained, but it needs two libraries to match python-pptx and is pre-1.0.
What would change this: if the main use turns out to be filling a fixed company template deck (swap text, tables and charts, drop and reorder slides), test pptx-automizer against python-pptx on the real template. If it wins there, PowerPoint could become the JavaScript exception; otherwise keep everything in Python.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- Out of MVP scope (`BUILD_PROMPT:65`). The Python verdict stands for later. Nothing here changes the MVP build.
