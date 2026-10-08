"""Data quality checks.

Two kinds:
- Rule checks: things that must always hold (no orphan claims, marts reconcile to staging).
- Statistical checks: today's metrics compared with a rolling baseline of previous runs,
  instead of a fixed threshold, so normal growth doesn't raise false alarms.
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    severity: str = "error"  # "error" blocks publishing; "warn" is reported only


def _scalar(db: sqlite3.Connection, sql: str, *params) -> float:
    return db.execute(sql, params).fetchone()[0] or 0


def orphan_claims(db: sqlite3.Connection) -> CheckResult:
    n = _scalar(db, """SELECT COUNT(*) FROM claims c
                       LEFT JOIN policies p ON p.policy_id = c.policy_id
                       WHERE p.policy_id IS NULL""")
    return CheckResult("orphan_claims", n == 0, f"{int(n)} claims reference a missing policy")


def loss_before_effective(db: sqlite3.Connection) -> CheckResult:
    n = _scalar(db, """SELECT COUNT(*) FROM claims c JOIN policies p ON p.policy_id = c.policy_id
                       WHERE c.loss_date < p.effective_date""")
    return CheckResult("loss_before_policy_effective", n == 0, f"{int(n)} claims have a loss date before the policy started")


def mart_reconciles(db: sqlite3.Connection) -> CheckResult:
    staging = _scalar(db, "SELECT SUM(written_premium) FROM policies")
    mart = _scalar(db, "SELECT SUM(written_premium) FROM mart_loss_ratio")
    staged_losses = _scalar(db, """SELECT SUM(c.paid_amount + c.reserve_amount) FROM claims c
                                   JOIN policies p ON p.policy_id = c.policy_id""")
    mart_losses = _scalar(db, "SELECT SUM(incurred_losses) FROM mart_loss_ratio")
    ok = staging == mart and staged_losses == mart_losses
    return CheckResult("mart_reconciles_to_staging", ok,
                       f"premium staging={int(staging)} mart={int(mart)}; losses staging={int(staged_losses)} mart={int(mart_losses)}")


def quarantine_rate(db: sqlite3.Connection, run_date: str, loaded: int, max_rate: float = 0.02) -> CheckResult:
    q = _scalar(db, "SELECT COUNT(*) FROM quarantine WHERE run_date = ?", run_date)
    total = loaded + q
    rate = q / total if total else 0
    return CheckResult("quarantine_rate", rate <= max_rate,
                       f"{int(q)} of {int(total)} rows quarantined ({rate:.1%}, limit {max_rate:.0%})")


def record_metric(db: sqlite3.Connection, run_date: str, metric: str, value: float) -> None:
    db.execute("INSERT OR REPLACE INTO run_metrics VALUES (?, ?, ?)", (run_date, metric, value))


def baseline_anomaly(db: sqlite3.Connection, run_date: str, metric: str, value: float,
                     window: int = 14, z_limit: float = 3.0, min_history: int = 5) -> CheckResult:
    """Flag `value` if it is more than `z_limit` standard deviations from the last `window` runs."""
    history = [r[0] for r in db.execute(
        "SELECT value FROM run_metrics WHERE metric = ? AND run_date < ? ORDER BY run_date DESC LIMIT ?",
        (metric, run_date, window))]
    if len(history) < min_history:
        return CheckResult(f"baseline:{metric}", True, f"only {len(history)} prior runs, baseline not established", "warn")
    mean = statistics.fmean(history)
    stdev = statistics.pstdev(history) or max(abs(mean) * 0.01, 1e-9)
    z = (value - mean) / stdev
    return CheckResult(f"baseline:{metric}", abs(z) <= z_limit,
                       f"value={value:.2f} mean={mean:.2f} stdev={stdev:.2f} z={z:+.2f}", "warn")


def run_all(db: sqlite3.Connection, run_date: str, loaded_rows: int) -> list[CheckResult]:
    results = [orphan_claims(db), loss_before_effective(db), mart_reconciles(db),
               quarantine_rate(db, run_date, loaded_rows)]
    metrics = {
        "claim_count": _scalar(db, "SELECT COUNT(*) FROM claims WHERE run_date = ?", run_date),
        "avg_paid": _scalar(db, "SELECT AVG(paid_amount) FROM claims WHERE run_date = ?", run_date),
    }
    for name, value in metrics.items():
        results.append(baseline_anomaly(db, run_date, name, value))
        record_metric(db, run_date, name, value)
    return results
