# Claims Pipeline

A small batch data pipeline for insurance policy and claims data: **ingest → validate/quarantine → transform (SQL marts) → data quality checks → publish or roll back**. It follows the same ETL pattern I've worked with on AWS (S3 → Glue → Redshift), scaled down to run anywhere with only the Python standard library and SQLite.

**Stack:** Python 3.10+ · SQL (SQLite) · unittest. No third-party dependencies.

## What it does

1. **Ingest with schema validation.** Each CSV row is parsed against a typed spec (dates, money as integer cents, required text). Bad rows (invalid dates, negative amounts, a claim reported before its loss date, duplicate keys) go to a **quarantine table with the reason**, instead of being dropped or failing the whole batch.
2. **Transform with SQL.** Builds two reporting marts:
   - `mart_loss_ratio`: written premium, incurred losses and loss ratio by state and line of business
   - `mart_claims_monthly`: claim counts, paid and reserved amounts, and average reporting lag by loss month
3. **Data quality checks.**
   - *Hard checks* (block publishing): no orphan claims, no losses before the policy effective date, marts reconcile to staging totals, quarantine rate under 2%.
   - *Statistical checks* (warnings): today's claim count and average paid amount are compared with a **rolling 14-run baseline** (z-score), so normal growth doesn't trigger fixed-threshold false alarms.
4. **All-or-nothing publish.** The whole batch runs in one transaction. If a hard check fails, everything is rolled back, so bad numbers never reach the marts.
5. **Run report.** A JSON summary with loaded and quarantined counts and every check result. The exit code is non-zero if the batch wasn't published, which suits a scheduler or CI.

## Run

```bash
python -m pipeline.cli sample --out data/sample                 # generate a sample batch (with a few bad rows)
python -m pipeline.cli run --input data/sample --db out/warehouse.db --run-date 2026-10-01
python -m unittest discover -s tests -t . -v                    # 6 tests
```

## Layout

```
pipeline/ingest.py       typed CSV parsing, quarantine, staging tables
pipeline/transform.py    SQL marts (CTEs, joins, aggregates, date math)
pipeline/checks.py       rule checks, reconciliation, rolling-baseline anomaly detection
pipeline/cli.py          orchestration + JSON run report
pipeline/sample_data.py  deterministic sample data generator
```

Built with AI coding tools; I designed the checks and data model from my experience with insurance data, and reviewed and tested the code.
