#!/usr/bin/env python3
"""Module A verification — runs the key smoke checks and prints real results."""
import os
import snowflake.connector
from cryptography.hazmat.primitives import serialization

with open(os.path.expanduser("~/.snowflake/rsa_key.p8"), "rb") as f:
    pkey = serialization.load_pem_private_key(f.read(), password=None)
conn = snowflake.connector.connect(
    account="unpsrpt-il63479", user="benjamin.atkinson@gmail.com",
    role="ACCOUNTADMIN", warehouse="RX_CORTEX_WH", private_key=pkey,
)
cur = conn.cursor()
cur.execute("USE DATABASE RX_INTELLIGENCE")

def q(sql, label):
    print(f"\n=== {label} ===")
    cur.execute(sql)
    rows = cur.fetchall()
    for r in rows:
        print("  ", r)
    return rows

q("SELECT 'RAW.SDUD_KY_TN' t, COUNT(*) n FROM RAW.SDUD_KY_TN "
  "UNION ALL SELECT 'RAW.NADAC_LATEST', COUNT(*) FROM RAW.NADAC_LATEST "
  "UNION ALL SELECT 'RAW.PARTD_I65', COUNT(*) FROM RAW.PARTD_I65 "
  "UNION ALL SELECT 'V_KY_TN_SPREAD_ANALYSIS', COUNT(*) FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS "
  "UNION ALL SELECT 'V_I65_PARTD_PRESCRIBING', COUNT(*) FROM ANALYTICS.V_I65_PARTD_PRESCRIBING",
  "1. Row counts (all must be non-zero)")

q("SELECT COUNT(*) bad_ndc FROM RAW.SDUD_KY_TN WHERE LENGTH(NDC11)<>11 OR NDC11 REGEXP '[^0-9]'",
  "2. SDUD NDC11 normalization violations (expect 0)")

q("SELECT COUNT(*) bad_ndc FROM RAW.NADAC_LATEST WHERE LENGTH(NDC)<>11 OR NDC REGEXP '[^0-9]'",
  "2b. NADAC NDC normalization violations (expect 0)")

q("SELECT COUNT(*) null_bench FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS WHERE NADAC_INGREDIENT_COST IS NULL OR PASS_THROUGH_BENCHMARK IS NULL",
  "3. Null benchmarks in spread view (expect 0)")

q("SELECT COUNT(*) neg_spread FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS WHERE ESTIMATED_SPREAD_DOLLARS < 0",
  "4a. Negative spread (expect 0)")

q("SELECT COUNT(*) bad_order FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS WHERE PASS_THROUGH_BENCHMARK < NADAC_INGREDIENT_COST",
  "4b. Benchmark < ingredient cost (expect 0)")

q("SELECT ROUND(SUM(TOTAL_REIMBURSED),0) medicaid_spend, ROUND(SUM(NADAC_INGREDIENT_COST),0) ingredient, "
  "ROUND(SUM(PASS_THROUGH_BENCHMARK),0) benchmark, ROUND(SUM(ESTIMATED_SPREAD_DOLLARS),0) spread_leakage, "
  "COUNT(DISTINCT NDC11) distinct_ndc FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS",
  "5. Spread headline numbers")

q("SELECT THERAPEUTIC_CLASS, COUNT(*) n FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS GROUP BY 1 ORDER BY 2 DESC",
  "6. Therapeutic class distribution")

q("SELECT METRO_CITY, STATE, COUNT(DISTINCT PRSCRBR_NPI) prescribers, ROUND(SUM(PARTD_DRUG_COST),0) total_cost "
  "FROM ANALYTICS.V_I65_PARTD_PRESCRIBING GROUP BY 1,2 ORDER BY 3 DESC",
  "7. Part D geo sanity (expect Louisville + Nashville)")

q("SELECT name, comment FROM INFORMATION_SCHEMA.SEMANTIC_VIEWS WHERE name='SV_TRANSPARENT_RX'",
  "8. Semantic view registered")

conn.close()
print("\nDONE")
