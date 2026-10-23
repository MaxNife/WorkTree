"""A minimal ``.docx`` writer for tests: the package parts are written directly as XML."""

from __future__ import annotations

import zipfile
from pathlib import Path

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)
SECTION = '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'


def paragraph(text: str, *, style: str = "", bold: bool = False) -> str:
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:p>{style_xml}<w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def simple_field(name: str, shown: str = "x") -> str:
    return (
        f'<w:fldSimple w:instr=" MERGEFIELD {name} \\* MERGEFORMAT">'
        f"<w:r><w:rPr><w:b/></w:rPr><w:t>{shown}</w:t></w:r></w:fldSimple>"
    )


def complex_field(name: str, shown: str = "x") -> str:
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> MERGEFIELD {name} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"<w:r><w:t>{shown}</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def write_docx(path: Path, body: str, *, core: str = "") -> Path:
    """Write a .docx whose body is the given WordprocessingML (a section is appended)."""
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}{SECTION}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
        if core:
            archive.writestr("docProps/core.xml", core)
    return path
