"""Deterministic SQLite General Ledger fixture used by SQL and matching tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def create_gl_database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE accounts (
                account_code TEXT PRIMARY KEY,
                account_name TEXT NOT NULL,
                currency TEXT NOT NULL
            );
            CREATE TABLE journal_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_code TEXT NOT NULL,
                posting_date TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT NOT NULL
            );
            CREATE TABLE load_stage (
                account_code TEXT,
                posting_date TEXT,
                amount REAL,
                description TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO accounts VALUES (?, ?, ?)",
            [
                ("1000", "Cash", "GBP"),
                ("2000", "Payables", "GBP"),
                ("3000", "Revenue", "GBP"),
            ],
        )
        connection.executemany(
            "INSERT INTO journal_lines (account_code, posting_date, amount, description) VALUES (?, ?, ?, ?)",
            [
                ("1000", "2026-01-01", 42.50, "Opening"),
                ("2000", "2026-01-02", -42.50, "Offset"),
                ("3000", "2026-01-03", 100.00, "Invoice"),
            ],
        )
        connection.commit()
    finally:
        connection.close()
    return path


__all__ = ["create_gl_database"]
