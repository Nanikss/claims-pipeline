"""Deterministic sample data generator (includes a few deliberately bad rows)."""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

STATES = ["CA", "NY", "TX", "FL", "IL"]
LINES = ["Commercial Property", "General Liability", "Commercial Auto"]


def write_batch(out_dir: Path, seed: int = 7, policies: int = 200, claims: int = 120) -> None:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    start = date(2025, 1, 1)
    policy_rows = []
    for i in range(1, policies + 1):
        eff = start + timedelta(days=rng.randrange(0, 365))
        policy_rows.append([f"POL-{i:05d}", rng.choice(STATES), rng.choice(LINES), eff.isoformat(),
                            f"{rng.randrange(2_000, 60_000)}.{rng.randrange(0, 100):02d}"])
    with (out_dir / "policies.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["policy_id", "state", "line", "effective_date", "written_premium"])
        w.writerows(policy_rows)
        w.writerow(["POL-BAD01", "CA", "General Liability", "2025-13-40", "1000"])  # invalid date

    with (out_dir / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "policy_id", "loss_date", "reported_date", "paid_amount", "reserve_amount"])
        for i in range(1, claims + 1):
            pol = rng.choice(policy_rows)
            loss = date.fromisoformat(pol[3]) + timedelta(days=rng.randrange(1, 300))
            reported = loss + timedelta(days=rng.randrange(0, 45))
            w.writerow([f"CLM-{i:05d}", pol[0], loss.isoformat(), reported.isoformat(),
                        f"{rng.randrange(0, 20_000)}.00", f"{rng.randrange(0, 15_000)}.00"])
        w.writerow(["CLM-BAD01", "POL-00001", "2025-06-10", "2025-06-01", "500.00", "0"])  # reported before loss
