import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline import checks, cli, ingest, sample_data


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.batch = self.tmp / "batch"
        sample_data.write_batch(self.batch, seed=1)
        self.db_path = self.tmp / "wh.db"

    def test_end_to_end_run_publishes_and_quarantines_bad_rows(self):
        report = cli.run(self.batch, self.db_path, "2026-10-01")
        self.assertTrue(report["published"])
        self.assertEqual(report["loaded"], {"policies": 200, "claims": 120})
        self.assertEqual(report["quarantined"], {"policies": 1, "claims": 1})
        with sqlite3.connect(self.db_path) as db:
            reasons = {r[0] for r in db.execute("SELECT reason FROM quarantine")}
            self.assertIn("reported before loss date", reasons)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mart_loss_ratio").fetchone()[0] > 0, True)

    def test_mart_reconciles_to_staging(self):
        cli.run(self.batch, self.db_path, "2026-10-01")
        with sqlite3.connect(self.db_path) as db:
            self.assertTrue(checks.mart_reconciles(db).passed)

    def test_orphan_claim_blocks_publishing_and_rolls_back(self):
        with (self.batch / "claims.csv").open("a", encoding="utf-8") as f:
            f.write("CLM-ORPHAN,POL-99999,2025-05-01,2025-05-02,100.00,0\n")
        report = cli.run(self.batch, self.db_path, "2026-10-01")
        self.assertFalse(report["published"])
        failed = [c["name"] for c in report["checks"] if not c["passed"]]
        self.assertIn("orphan_claims", failed)
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0], 0)  # nothing published

    def test_amounts_are_parsed_to_integer_cents(self):
        self.assertEqual(ingest._cents("19.99"), 1999)
        self.assertEqual(ingest._cents("0.1"), 10)
        with self.assertRaises(ValueError):
            ingest._cents("-5")

    def test_baseline_anomaly_needs_history_then_flags_outliers(self):
        db = sqlite3.connect(":memory:")
        ingest.create_schema(db)
        self.assertEqual(checks.baseline_anomaly(db, "2026-10-01", "claim_count", 100).severity, "warn")
        for day, v in enumerate([100, 104, 98, 101, 99, 103, 97], start=1):
            checks.record_metric(db, f"2026-09-{day:02d}", "claim_count", v)
        self.assertTrue(checks.baseline_anomaly(db, "2026-10-01", "claim_count", 102).passed)
        self.assertFalse(checks.baseline_anomaly(db, "2026-10-01", "claim_count", 160).passed)

    def test_missing_column_fails_fast(self):
        (self.batch / "policies.csv").write_text("policy_id,state\nPOL-1,CA\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            cli.run(self.batch, self.db_path, "2026-10-01")


if __name__ == "__main__":
    unittest.main()
