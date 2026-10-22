# Research 09: HTML (2026-09-29)

## Parsing (Python, licences from PyPI)
- BeautifulSoup 4.15.0 (MIT), lxml 6.1.3 (BSD-3), html5lib 1.1 (MIT, last release 2020), selectolax 0.4.13 (MIT).
- TESTED: bs4 + html5lib repaired badly broken HTML (unclosed table cells and rows) and extracted the table; `pandas.read_html` turned the repaired table into typed records (rates became numbers).

## Generating (Python)
- Jinja2 3.1.6 (BSD): TESTED, renders tables with formatting (e.g. `1500.50`). Good for report and email bodies.
- WeasyPrint 70.0 (BSD) for HTML to PDF: not tested here.

## Pages that need JavaScript, and HTML to PDF
- Playwright (approved): TESTED that it sees a table built by JavaScript after load (`wait_for_selector`), that `pandas.read_html` can then read it from `page.content()`, and that `page.pdf()` and `page.screenshot()` work. So Playwright covers scraping, PDF and screenshots.

## .NET (from each project's README)
- AngleSharp: MIT. HTML5 parser building a standards-based DOM with CSS selectors; does not execute JavaScript.
- HtmlAgilityPack: MIT. Very tolerant of malformed HTML; XPath (README does not mention CSS selectors or HTML5 compliance).

## Elsa
No HTML-specific activities. Elsa has Liquid as an expression syntax (module `Elsa.Expressions.Liquid` exists; not examined for template rendering) and an HTTP module.

## Verdict (Python-only view from 2026-09-29; superseded by the language verdict below)
Python worker (bs4/lxml + pandas.read_html for parsing, Jinja2 for generation, Playwright for JavaScript pages and PDF).

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [measured] = run in this sandbox on 2026-09-30; [tested] = capability tested, no timing; [docs] = README/page; [reasoning] = inference.
.NET limit: NuGet is blocked in the sandbox, so AngleSharp and HtmlAgilityPack could NOT be run. They are [docs] only.

### Parsing broken HTML [tested]
Same input as before: a table with unclosed cells and rows, plus an unclosed paragraph and bold tag.
| Language | Library | Result |
|---|---|---|
| Python | bs4 + html5lib, then `pandas.read_html` | repaired, typed records in one call (earlier test) |
| JavaScript | cheerio 1.2.0 (MIT) | repaired: 3 rows, and 6 lines of code turned them into `{"Ccy":"USD","Rate":1500.5}` style records (numbers typed by my code, not the library) |
| JavaScript | jsdom 30.1.1 (MIT) | repaired: 3 rows, 2 cells in the data row |
| .NET | AngleSharp / HtmlAgilityPack | README says both handle malformed HTML; not run [docs] |
Both JS libraries follow the browser's HTML5 repair rules, so they are as tolerant as Python's html5lib. The difference is convenience: `pandas.read_html` gives typed tables directly; in JS the table-to-records step is hand-written.

### Generating HTML [tested for Python only]
Jinja2 rendering was tested (Python). JavaScript equivalents (nunjucks 3.2.4 last released 2023-04, handlebars 4.7.9) were NOT tested. .NET options (Liquid via Fluid, Scriban, Razor) not researched.

### JavaScript-rendered pages, PDF, screenshots
That is Playwright's job in any language (see the Playwright verdict in research-01). Measured with a table built by JavaScript 300 ms after load: Node 1.43 s total (591 ms browser launch), Python 1.38 s total (725 ms launch); both read the table, wrote a PDF and a screenshot [measured].

### VERDICT: Python for the HTML parse-and-generate tool; the browser-driven parts are Playwright (multi-language allowed)
Reason: as a "linear" tool the HTML node should live in one language. Python matches JavaScript on parsing correctness and beats it on convenience (`pandas.read_html`, Jinja2 already tested), and it keeps the output in the same pandas world as the Excel and CSV tools. .NET is unproven here.
JavaScript is a legitimate second choice: cheerio/jsdom behave like a browser, which is a plus for scraping. If the team writes scraping scripts in JS anyway, keep them inside Playwright script nodes, not a separate HTML tool.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- Out of MVP scope (`BUILD_PROMPT:65`). The Python verdict stands for later. Nothing here changes the MVP build.
