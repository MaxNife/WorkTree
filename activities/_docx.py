"""Plain-XML helpers for ``.docx`` files (zipfile + lxml): text, info, rendering and mail merge.

The mail-merge approach follows WordCraft (CraftApps, MIT OR Apache-2.0): ``MERGEFIELD`` fields,
either a single ``w:fldSimple`` or a ``w:fldChar`` begin/separate/end run sequence, are replaced by
the record's value, with one copy of the body per record. Only the main document body is merged;
headers and footers are copied unchanged. Input files are untrusted: XML is parsed without entity
resolution or network access, and the document part is size-capped.
"""

from __future__ import annotations

import copy
import html
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MAX_PART_BYTES = 64 * 1024 * 1024
DOCUMENT_PART = "word/document.xml"
CORE_PART = "docProps/core.xml"
_MERGE_FIELD = re.compile(r'^\s*MERGEFIELD\s+(?:\\\S+\s+)*(?:"([^"]+)"|([^\s"\\]+))', re.IGNORECASE)
_HEADING = re.compile(r"heading\s*(\d)", re.IGNORECASE)


def w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _parser() -> Any:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def read_part(path: Path, name: str, *, required: bool = True) -> bytes | None:
    with zipfile.ZipFile(path) as archive:
        try:
            info = archive.getinfo(name)
        except KeyError:
            if required:
                raise ValueError(f"not a valid .docx: missing {name}") from None
            return None
        if info.file_size > MAX_PART_BYTES:
            raise ValueError(f"{name} is too large")
        return archive.read(info)


def load_document(path: Path) -> Any:
    try:
        data = read_part(path, DOCUMENT_PART)
    except zipfile.BadZipFile:
        raise ValueError(f"{path.name} is not a .docx file") from None
    assert data is not None
    return etree.fromstring(data, _parser())


def paragraph_text(paragraph: Any) -> str:
    out: list[str] = []
    for node in paragraph.iter():
        if node.tag == w("t"):
            out.append(node.text or "")
        elif node.tag == w("tab"):
            out.append("\t")
        elif node.tag in (w("br"), w("cr")):
            out.append("\n")
    return "".join(out)


def body_blocks(root: Any) -> list[Any]:
    body = root.find(w("body"))
    return [child for child in body if child.tag in (w("p"), w("tbl"))] if body is not None else []


def plain_text(root: Any) -> str:
    lines: list[str] = []
    for block in body_blocks(root):
        if block.tag == w("p"):
            lines.append(paragraph_text(block))
        else:
            for row in block.iter(w("tr")):
                cells = [
                    "\n".join(paragraph_text(p) for p in c.iter(w("p"))) for c in row.iter(w("tc"))
                ]
                lines.append("\t".join(cells))
    return "\n".join(lines)


def merge_field_names(root: Any) -> list[str]:
    names: list[str] = []
    for node in root.iter(w("fldSimple")):
        match = _MERGE_FIELD.match(node.get(w("instr"), ""))
        if match:
            names.append(match.group(1) or match.group(2))
    for node in root.iter(w("instrText")):
        match = _MERGE_FIELD.match(node.text or "")
        if match:
            names.append(match.group(1) or match.group(2))
    return list(dict.fromkeys(names))


def info(path: Path, root: Any) -> dict[str, Any]:
    text = plain_text(root)
    result: dict[str, Any] = {
        "paragraphs": len(list(root.iter(w("p")))),
        "tables": len(list(root.iter(w("tbl")))),
        "words": len(text.split()),
        "characters": len(text),
        "merge_fields": merge_field_names(root),
        "tracked_changes": any(True for _ in root.iter(w("ins"), w("del"))),
    }
    core = read_part(path, CORE_PART, required=False)
    if core:
        meta = etree.fromstring(core, _parser())
        for child in meta:
            name = etree.QName(child).localname
            if name in ("title", "subject", "creator", "lastModifiedBy", "created", "modified"):
                result[name] = child.text or ""
    return result


# ---------------------------------------------------------------------------- rendering
def _flag(properties: Any, tag: str) -> bool:
    node = properties.find(w(tag)) if properties is not None else None
    return node is not None and node.get(w("val"), "true").lower() not in ("0", "false", "off")


def _runs(paragraph: Any) -> list[tuple[str, bool, bool]]:
    pieces: list[tuple[str, bool, bool]] = []
    for run in paragraph.iter(w("r")):
        text = paragraph_text(run)
        if text:
            properties = run.find(w("rPr"))
            pieces.append((text, _flag(properties, "b"), _flag(properties, "i")))
    return pieces


def _paragraph_kind(paragraph: Any) -> tuple[int, int | None]:
    """(heading level or 0, list level or None)."""
    properties = paragraph.find(w("pPr"))
    heading = 0
    level: int | None = None
    if properties is not None:
        style = properties.find(w("pStyle"))
        if style is not None:
            name = style.get(w("val"), "")
            found = _HEADING.search(name)
            heading = int(found.group(1)) if found else (1 if name.lower() == "title" else 0)
        numbering = properties.find(w("numPr"))
        if numbering is not None:
            ilvl = numbering.find(w("ilvl"))
            level = int(ilvl.get(w("val"), "0")) if ilvl is not None else 0
    return heading, level


def _md_inline(paragraph: Any) -> str:
    out = ""
    for text, bold, italic in _runs(paragraph):
        if text.strip() and bold:
            text = f"**{text}**"
        if text.strip() and italic:
            text = f"*{text}*"
        out += text
    return out.replace("\n", "  \n")


def render_markdown(root: Any) -> str:
    lines: list[str] = []
    for block in body_blocks(root):
        if block.tag == w("p"):
            heading, level = _paragraph_kind(block)
            text = _md_inline(block)
            if heading:
                lines.append(f"{'#' * min(heading, 6)} {text}")
            elif level is not None:
                lines.append(f"{'  ' * level}- {text}")
            else:
                lines.append(text)
            lines.append("")
        else:
            rows = [
                [" ".join(paragraph_text(p) for p in c.iter(w("p"))) for c in row.iter(w("tc"))]
                for row in block.iter(w("tr"))
            ]
            if rows:
                width = max(len(row) for row in rows)
                padded = [[*row, *[""] * (width - len(row))] for row in rows]
                lines.append("| " + " | ".join(padded[0]) + " |")
                lines.append("|" + " --- |" * width)
                lines.extend("| " + " | ".join(row) + " |" for row in padded[1:])
                lines.append("")
    return "\n".join(lines).strip() + "\n"


def _html_inline(paragraph: Any) -> str:
    out = ""
    for text, bold, italic in _runs(paragraph):
        piece = html.escape(text).replace("\n", "<br>")
        if bold:
            piece = f"<strong>{piece}</strong>"
        if italic:
            piece = f"<em>{piece}</em>"
        out += piece
    return out


def render_html(root: Any, title: str) -> str:
    parts: list[str] = []
    in_list = False
    for block in body_blocks(root):
        heading, level = _paragraph_kind(block) if block.tag == w("p") else (0, None)
        if in_list and level is None:
            parts.append("</ul>")
            in_list = False
        if block.tag == w("p"):
            text = _html_inline(block)
            if heading:
                parts.append(f"<h{min(heading, 6)}>{text}</h{min(heading, 6)}>")
            elif level is not None:
                if not in_list:
                    parts.append("<ul>")
                    in_list = True
                parts.append(f"<li>{text}</li>")
            else:
                parts.append(f"<p>{text}</p>")
        else:
            rows = []
            for row in block.iter(w("tr")):
                cells = "".join(
                    f"<td>{html.escape(' '.join(paragraph_text(p) for p in c.iter(w('p'))))}</td>"
                    for c in row.iter(w("tc"))
                )
                rows.append(f"<tr>{cells}</tr>")
            parts.append("<table>" + "".join(rows) + "</table>")
    if in_list:
        parts.append("</ul>")
    return (
        '<!doctype html>\n<html><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title></head><body>\n"
        + "\n".join(parts)
        + "\n</body></html>\n"
    )


# ---------------------------------------------------------------------------- mail merge
def _value_run(value: str, properties: Any) -> Any:
    run = etree.Element(w("r"))
    if properties is not None:
        run.append(copy.deepcopy(properties))
    for index, line in enumerate(value.split("\n")):
        if index:
            etree.SubElement(run, w("br"))
        text = etree.SubElement(run, w("t"))
        text.text = line
        text.set(f"{{{XML_NS}}}space", "preserve")
    return run


def _lookup(record: dict[str, str], name: str) -> str:
    if name in record:
        return record[name]
    folded = name.casefold()
    for key, value in record.items():
        if key.casefold() == folded:
            return value
    return ""


def _fill_simple_fields(block: Any, record: dict[str, str]) -> None:
    for field in list(block.iter(w("fldSimple"))):
        match = _MERGE_FIELD.match(field.get(w("instr"), ""))
        if not match:
            continue
        inner = field.find(w("r"))
        properties = inner.find(w("rPr")) if inner is not None else None
        replacement = _value_run(_lookup(record, (match.group(1) or match.group(2))), properties)
        field.getparent().replace(field, replacement)


def _fill_complex_fields(paragraph: Any, record: dict[str, str]) -> None:
    children = list(paragraph)
    index = 0
    while index < len(children):
        begin = children[index]
        marker = begin.find(w("fldChar")) if begin.tag == w("r") else None
        if marker is None or marker.get(w("fldCharType")) != "begin":
            index += 1
            continue
        depth, end, separate = 0, None, None
        instruction = ""
        for scan in range(index, len(children)):
            run = children[scan]
            if run.tag != w("r"):
                continue
            kind = run.find(w("fldChar"))
            kind_type = kind.get(w("fldCharType")) if kind is not None else None
            if kind_type == "begin":
                depth += 1
            elif kind_type == "separate" and depth == 1:
                separate = scan
            elif kind_type == "end":
                depth -= 1
                if depth == 0:
                    end = scan
                    break
            elif separate is None and depth == 1:
                instruction += "".join(t.text or "" for t in run.iter(w("instrText")))
        match = _MERGE_FIELD.match(instruction)
        if end is None or not match:
            index += 1
            continue
        result_runs = children[separate + 1 : end] if separate is not None else []
        source = next((r for r in result_runs if r.tag == w("r")), begin)
        replacement = _value_run(
            _lookup(record, (match.group(1) or match.group(2))), source.find(w("rPr"))
        )
        anchor = children[index]
        anchor.addprevious(replacement)
        for run in children[index : end + 1]:
            paragraph.remove(run)
        children = list(paragraph)
        index = children.index(replacement) + 1


def _section_end(blocks: list[Any], section: Any) -> None:
    """End a record's section: its last paragraph carries a copy of the body section properties
    that starts the following section on a new page."""
    last = blocks[-1] if blocks else None
    if last is None or last.tag != w("p"):
        last = etree.Element(w("p"))
        if blocks:
            blocks[-1].addnext(last)
        blocks.append(last)
    properties = last.find(w("pPr"))
    if properties is None:
        properties = etree.Element(w("pPr"))
        last.insert(0, properties)
    for old in properties.findall(w("sectPr")):
        properties.remove(old)
    properties.append(
        _next_page(copy.deepcopy(section) if section is not None else etree.Element(w("sectPr")))
    )


def _next_page(section: Any) -> Any:
    kind = section.find(w("type"))
    if kind is None:
        kind = etree.Element(w("type"))
        anchor = [c for c in section if c.tag in (w("headerReference"), w("footerReference"))]
        if anchor:
            anchor[-1].addnext(kind)
        else:
            section.insert(0, kind)
    kind.set(w("val"), "nextPage")
    return section


def _unique_drawing_ids(root: Any) -> None:
    """Copying the body repeats ``wp:docPr`` ids; Word wants them unique per document."""
    counter = 0
    for node in root.iter():
        if isinstance(node.tag, str) and node.tag.endswith("}docPr"):
            counter += 1
            node.set("id", str(counter))


def merge_document(template: Path, records: list[dict[str, str]], target: Path) -> int:
    """Write ``target``: the template body once per record, each record its own section."""
    root = load_document(template)
    body = root.find(w("body"))
    if body is None:
        raise ValueError("the template has no document body")
    section = body.find(w("sectPr"))
    templates = [child for child in body if child is not section]
    for child in templates:
        body.remove(child)
    last_index = len(records) - 1
    for number, record in enumerate(records):
        copies = [copy.deepcopy(child) for child in templates]
        for block in copies:
            _fill_simple_fields(block, record)
            for paragraph in list(block.iter(w("p"))):
                _fill_complex_fields(paragraph, record)
        if number < last_index:
            _section_end(copies, section)
        for block in copies:
            if section is not None:
                section.addprevious(block)
            else:
                body.append(block)
    if section is not None and last_index > 0:
        _next_page(section)
    _unique_drawing_ids(root)
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    _rewrite(template, target, {DOCUMENT_PART: data})
    return len(records)


def _rewrite(source: Path, target: Path, replacements: dict[str, bytes]) -> None:
    """Copy ``source`` to ``target`` replacing some parts; all other members are copied as-is."""
    temp = target.with_name(f".{target.name}.uaf-tmp")
    try:
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(temp, "w") as dst:
            for item in src.infolist():
                if item.filename in replacements:
                    dst.writestr(
                        item, replacements[item.filename], compress_type=item.compress_type
                    )
                else:
                    dst.writestr(item, src.read(item), compress_type=item.compress_type)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
