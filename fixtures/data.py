"""Deterministic data generators for fixture tests and local acceptance runs.

The large files are written at test time into an ignored directory. Nothing here produces
data at import time, so a checkout stays small.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyzipper
from openpyxl import Workbook

ZIP_PASSWORD = "fixture-zip-password"
CSV_HEADER = "invoice_id,supplier,amount,currency,posted_at\n"
FIXED_WIDTH_WIDTHS: tuple[tuple[str, int], ...] = (
    ("invoice_id", 10),
    ("supplier", 24),
    ("amount", 12),
    ("posted_at", 10),
)


def _invoice_line(index: int) -> str:
    return (
        f"INV-{index:07d},Supplier {index % 97:02d},"
        f"{(index % 10_000) / 100:.2f},GBP,2026-01-{(index % 28) + 1:02d}\n"
    )


def generate_encrypted_invoice_zip(
    path: Path,
    *,
    rows: int = 1_000_000,
    password: str = ZIP_PASSWORD,
) -> Path:
    """Write a 1M-row CSV inside an AES-256 ZIP without holding it all in memory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with pyzipper.AESZipFile(
        path,
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        compresslevel=1,
        encryption=pyzipper.WZ_AES,
    ) as archive:
        archive.setpassword(password.encode("utf-8"))
        archive.setencryption(pyzipper.WZ_AES, nbits=256)
        with archive.open("invoices.csv", "w", force_zip64=True) as handle:
            handle.write(CSV_HEADER.encode("utf-8"))
            buffer = bytearray()
            for index in range(rows):
                buffer.extend(_invoice_line(index).encode("utf-8"))
                if len(buffer) >= 1_000_000:
                    handle.write(buffer)
                    buffer.clear()
            if buffer:
                handle.write(buffer)
    return path


def generate_excel(path: Path, *, rows: int = 500) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Invoices")
    sheet.append(["invoice_id", "supplier", "amount", "currency", "posted_at"])
    for index in range(rows):
        sheet.append(
            [
                f"INV-{index:07d}",
                f"Supplier {index % 97:02d}",
                round((index % 10_000) / 100, 2),
                "GBP",
                f"2026-01-{(index % 28) + 1:02d}",
            ]
        )
    workbook.save(path)
    return path


def fixed_width_row(index: int) -> str:
    values = {
        "invoice_id": f"INV{index:07d}",
        "supplier": f"Supplier {index % 97:02d}",
        "amount": f"{(index % 10_000) / 100:.2f}",
        "posted_at": f"2026-01-{(index % 28) + 1:02d}",
    }
    return "".join(values[name].ljust(width) for name, width in FIXED_WIDTH_WIDTHS) + "\n"


def parse_fixed_width(line: str) -> dict[str, str]:
    values: dict[str, str] = {}
    offset = 0
    for name, width in FIXED_WIDTH_WIDTHS:
        values[name] = line[offset : offset + width].strip()
        offset += width
    return values


def generate_fixed_width(path: Path, *, rows: int = 1_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for index in range(rows):
            handle.write(fixed_width_row(index))
    return path


def generate_log_file(path: Path, *, rows: int = 1_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for index in range(rows):
            moment = (start + timedelta(seconds=index)).isoformat().replace("+00:00", "Z")
            level = "ERROR" if index % 50 == 0 else "INFO"
            handle.write(
                f"{moment} {level} worker={index % 4} "
                f'invoice=INV-{index:07d} message="batch line {index}"\n'
            )
    return path


def generate_all(
    directory: Path,
    *,
    big_rows: int = 1_000_000,
    sample_rows: int = 500,
) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return {
        "encrypted_zip": generate_encrypted_invoice_zip(directory / "invoices.zip", rows=big_rows),
        "excel": generate_excel(directory / "invoices.xlsx", rows=sample_rows),
        "fixed_width": generate_fixed_width(directory / "invoices.fixed", rows=sample_rows),
        "log": generate_log_file(directory / "invoices.log", rows=sample_rows),
    }


__all__ = [
    "CSV_HEADER",
    "FIXED_WIDTH_WIDTHS",
    "ZIP_PASSWORD",
    "fixed_width_row",
    "generate_all",
    "generate_encrypted_invoice_zip",
    "generate_excel",
    "generate_fixed_width",
    "generate_log_file",
    "parse_fixed_width",
]
