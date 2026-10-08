"""Command-line entry point.

    python -m pipeline.cli run --input data/sample --db out/warehouse.db --run-date 2026-10-01
    python -m pipeline.cli sample --out data/sample
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import checks, ingest, sample_data, transform


def run(input_dir: Path, db_path: Path, run_date: str) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    try:
        ingest.create_schema(db)
        p_loaded, p_bad = ingest.load_csv(db, input_dir / "policies.csv", ingest.POLICIES, run_date)
        c_loaded, c_bad = ingest.load_csv(db, input_dir / "claims.csv", ingest.CLAIMS, run_date)
        transform.build_marts(db)
        results = checks.run_all(db, run_date, p_loaded + c_loaded)
        blocking = [r for r in results if not r.passed and r.severity == "error"]
        if blocking:
            db.rollback()  # never publish marts that fail a hard check
        else:
            db.commit()
        return {
            "run_date": run_date,
            "loaded": {"policies": p_loaded, "claims": c_loaded},
            "quarantined": {"policies": p_bad, "claims": c_bad},
            "published": not blocking,
            "checks": [r.__dict__ for r in results],
        }
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ingest, transform and check one batch")
    r.add_argument("--input", type=Path, required=True)
    r.add_argument("--db", type=Path, required=True)
    r.add_argument("--run-date", required=True)
    s = sub.add_parser("sample", help="generate a sample input batch")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    if args.cmd == "sample":
        sample_data.write_batch(args.out, seed=args.seed)
        print(f"Sample batch written to {args.out}")
        return 0
    report = run(args.input, args.db, args.run_date)
    print(json.dumps(report, indent=2))
    return 0 if report["published"] else 1


if __name__ == "__main__":
    sys.exit(main())
