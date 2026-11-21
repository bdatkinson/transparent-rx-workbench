-- =============================================================================
-- smoke_test.sql — Module A verification queries (run after analytics_ddl.sql)
-- =============================================================================
USE DATABASE RX_INTELLIGENCE;

-- 1. Row-count thresholds (all non-zero per definition-of-done)
SELECT 'RAW.SDUD_KY_TN'   AS tbl, COUNT(*) AS rows_ FROM RAW.SDUD_KY_TN
UNION ALL SELECT 'RAW.NADAC_LATEST', COUNT(*) FROM RAW.NADAC_LATEST
UNION ALL SELECT 'RAW.PARTD_I65',    COUNT(*) FROM RAW.PARTD_I65
UNION ALL SELECT 'ANALYTICS.V_KY_TN_SPREAD_ANALYSIS', COUNT(*) FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS
UNION ALL SELECT 'ANALYTICS.V_I65_PARTD_PRESCRIBING', COUNT(*) FROM ANALYTICS.V_I65_PARTD_PRESCRIBING;

-- 2. NDC normalization: every NDC11 is exactly 11 digits, no non-digits
SELECT COUNT(*) AS bad_ndc_sdud FROM RAW.SDUD_KY_TN
 WHERE LENGTH(NDC11) <> 11 OR NDC11 REGEXP '[^0-9]';
SELECT COUNT(*) AS bad_ndc_nadac FROM RAW.NADAC_LATEST
 WHERE LENGTH(NDC) <> 11 OR NDC REGEXP '[^0-9]';

-- 3. Join integrity: zero NULL benchmarks in the spread view (inner join, NADAC not null)
SELECT COUNT(*) AS null_benchmark_rows FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS
 WHERE NADAC_INGREDIENT_COST IS NULL OR PASS_THROUGH_BENCHMARK IS NULL;

-- 4. Spread formula invariants: spread >= 0, benchmark >= ingredient cost
SELECT COUNT(*) AS negative_spread FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS
 WHERE ESTIMATED_SPREAD_DOLLARS < 0;
SELECT COUNT(*) AS benchmark_lt_ingredient FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS
 WHERE PASS_THROUGH_BENCHMARK < NADAC_INGREDIENT_COST;

-- 5. Therapeutic class coverage (no NULLs)
SELECT THERAPEUTIC_CLASS, COUNT(*) AS n
  FROM ANALYTICS.V_KY_TN_SPREAD_ANALYSIS GROUP BY 1 ORDER BY 2 DESC;

-- 6. Part D geo sanity: only two metros, coordinates present
SELECT METRO_CITY, STATE, COUNT(DISTINCT PRSCRBR_NPI) AS prescribers,
       SUM(PARTD_DRUG_COST) AS total_cost
  FROM ANALYTICS.V_I65_PARTD_PRESCRIBING
 GROUP BY 1, 2 ORDER BY 3 DESC;

-- 7. Semantic view registered
SHOW SEMANTIC VIEWS LIKE 'SV_TRANSPARENT_RX';
SHOW SEMANTIC METRICS IN SEMANTIC VIEW ANALYTICS.SV_TRANSPARENT_RX;
