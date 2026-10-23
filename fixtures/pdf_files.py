"""Tiny PDF writers for tests: text pages and a one-page AcroForm, with no PDF library."""

from __future__ import annotations

from pathlib import Path


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble(objects: list[bytes]) -> bytes:
    """Number the bodies 1..n, then add the xref table and trailer (object 1 is the catalog)."""
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def write_text_pdf(path: Path, pages: list[str]) -> Path:
    """Write a PDF with one page per string; newlines in a string become separate lines."""
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(len(pages)))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, text in enumerate(pages):
        content_number = 5 + 2 * index
        lines = text.split("\n")
        body = "BT /F1 12 Tf 14 TL 72 720 Td\n" + "\n".join(
            f"({_escape(line)}) Tj T*" for line in lines
        )
        stream = (body + "\nET").encode("latin-1", errors="replace")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_number} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    path.write_bytes(_assemble(objects))
    return path


def write_form_pdf(path: Path, fields: list[str]) -> Path:
    """Write a one-page PDF whose AcroForm has one empty text field per name."""
    first = 6
    refs = " ".join(f"{first + index} 0 R" for index in range(len(fields)))
    objects: list[bytes] = [
        f"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [{refs}] /DR << /Font << /Helv 3 0 R >> >> "
        "/DA (/Helv 12 Tf 0 g) >> >>".encode(),
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R /Annots [{refs}] "
        "/Resources << /Font << /Helv 3 0 R >> >> >>".encode(),
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    for index, name in enumerate(fields):
        top = 700 - 30 * index
        objects.append(
            f"<< /Type /Annot /Subtype /Widget /FT /Tx /T ({_escape(name)}) /DA (/Helv 12 Tf 0 g) "
            f"/Rect [72 {top - 20} 300 {top}] /P 4 0 R /F 4 >>".encode()
        )
    path.write_bytes(_assemble(objects))
    return path
