"""Load raw CSV files into staging tables, validating each row against a schema.

Rows that fail validation are not dropped silently: they go to a quarantine table
with the reason, so they can be fixed and replayed.
"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

Parser = Callable[[str], object]


def _iso_date(v: str) -> str:
    return date.fromisoformat(v).isoformat()


def _cents(v: str) -> int:
    amount = round(float(v) * 100)
    if amount < 0:
        raise ValueError("negative amount")
    return amount


def _text(v: str) -> str:
    if not v.strip():
        raise ValueError("empty")
    return v.strip()


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: str
    columns: dict[str, Parser]


POLICIES = TableSpec("policies", "policy_id", {
    "policy_id": _text,
    "state": lambda v: _text(v).upper(),
    "line": _text,
    "effective_date": _iso_date,
    "written_premium": _cents,
})

CLAIMS = TableSpec("claims", "claim_id", {
    "claim_id": _text,
    "policy_id": _text,
    "loss_date": _iso_date,
    "reported_date": _iso_date,
    "paid_amount": _cents,
    "reserve_amount": _cents,
})


def create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS policies (
            policy_id TEXT PRIMARY KEY, state TEXT NOT NULL, line TEXT NOT NULL,
            effective_date TEXT NOT NULL, written_premium INTEGER NOT NULL, run_date TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL, loss_date TEXT NOT NULL,
            reported_date TEXT NOT NULL, paid_amount INTEGER NOT NULL, reserve_amount INTEGER NOT NULL,
            run_date TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quarantine (
            run_date TEXT NOT NULL, source TEXT NOT NULL, line_no INTEGER NOT NULL,
            raw TEXT NOT NULL, reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS run_metrics (
            run_date TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL,
            PRIMARY KEY (run_date, metric));
    """)


def load_csv(db: sqlite3.Connection, path: Path, spec: TableSpec, run_date: str) -> tuple[int, int]:
    """Validate and upsert rows. Returns (loaded, quarantined)."""
    loaded = quarantined = 0
    seen_keys: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(spec.columns) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
        for line_no, raw in enumerate(reader, start=2):
            try:
                row = {col: parse(raw[col]) for col, parse in spec.columns.items()}
                if spec is CLAIMS and row["reported_date"] < row["loss_date"]:
                    raise ValueError("reported before loss date")
                if row[spec.key] in seen_keys:
                    raise ValueError(f"duplicate {spec.key} in file")
            except (ValueError, KeyError) as e:
                db.execute("INSERT INTO quarantine VALUES (?, ?, ?, ?, ?)",
                           (run_date, spec.name, line_no, str(dict(raw)), str(e)))
                quarantined += 1
                continue
            seen_keys.add(row[spec.key])
            cols = list(spec.columns) + ["run_date"]
            db.execute(
                f"INSERT OR REPLACE INTO {spec.name} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [*row.values(), run_date],
            )
            loaded += 1
    return loaded, quarantined
