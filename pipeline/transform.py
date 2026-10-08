"""Build reporting marts from staging tables with plain SQL."""
from __future__ import annotations

import sqlite3

MART_SQL = """
DROP TABLE IF EXISTS mart_loss_ratio;
CREATE TABLE mart_loss_ratio AS
WITH claim_totals AS (
    SELECT policy_id, SUM(paid_amount + reserve_amount) AS incurred
    FROM claims GROUP BY policy_id
)
SELECT p.state,
       p.line,
       COUNT(*)                                   AS policies,
       SUM(p.written_premium)                     AS written_premium,
       COALESCE(SUM(c.incurred), 0)               AS incurred_losses,
       ROUND(1.0 * COALESCE(SUM(c.incurred), 0) / SUM(p.written_premium), 4) AS loss_ratio
FROM policies p
LEFT JOIN claim_totals c ON c.policy_id = p.policy_id
GROUP BY p.state, p.line;

DROP TABLE IF EXISTS mart_claims_monthly;
CREATE TABLE mart_claims_monthly AS
SELECT substr(loss_date, 1, 7)                               AS loss_month,
       COUNT(*)                                              AS claim_count,
       SUM(paid_amount)                                      AS paid,
       SUM(reserve_amount)                                   AS reserved,
       ROUND(AVG(julianday(reported_date) - julianday(loss_date)), 1) AS avg_report_lag_days
FROM claims
GROUP BY loss_month
ORDER BY loss_month;
"""


def build_marts(db: sqlite3.Connection) -> None:
    # Run statement by statement: executescript() would COMMIT first, which would
    # defeat the "roll back the whole batch if a hard check fails" guarantee.
    for statement in MART_SQL.split(";"):
        if statement.strip():
            db.execute(statement)
