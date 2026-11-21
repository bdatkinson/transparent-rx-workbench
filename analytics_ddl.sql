-- =============================================================================
-- analytics_ddl.sql — Module A, Step 4: analytical views + semantic view
-- Transparent Rx Intelligence Workbench (AffirmedRx demo)
-- Run as ACCOUNTADMIN after ingest_rx_data.py has loaded the RAW tables.
-- =============================================================================
USE DATABASE RX_INTELLIGENCE;
USE SCHEMA ANALYTICS;

-- ---------------------------------------------------------------------------
-- 1. V_KY_TN_SPREAD_ANALYSIS
--    Medicaid SDUD (KY+TN) aggregated to NDC x state x quarter, joined to the
--    NADAC benchmark, with the spread-pricing formula applied per claim.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_KY_TN_SPREAD_ANALYSIS AS
WITH sdud_agg AS (
    SELECT
        STATE,
        YEAR,
        QUARTER,
        NDC11,
        MAX(PRODUCT_NAME)                     AS PRODUCT_NAME,
        SUM(UNITS_REIMBURSED)                 AS UNITS_REIMBURSED,
        SUM(NUMBER_OF_PRESCRIPTIONS)          AS RX_COUNT,
        SUM(TOTAL_AMOUNT_REIMBURSED)          AS TOTAL_REIMBURSED
    FROM RX_INTELLIGENCE.RAW.SDUD_KY_TN
    WHERE UNITS_REIMBURSED > 0
      AND NUMBER_OF_PRESCRIPTIONS > 0
      AND TOTAL_AMOUNT_REIMBURSED > 0
    GROUP BY STATE, YEAR, QUARTER, NDC11
)
SELECT
    s.STATE,
    s.YEAR,
    s.QUARTER,
    s.NDC11,
    s.PRODUCT_NAME                                                             AS DRUG_NAME,
    n.NDC_DESCRIPTION,
    s.UNITS_REIMBURSED,
    s.RX_COUNT,
    s.TOTAL_REIMBURSED,
    ROUND(s.UNITS_REIMBURSED * n.NADAC_PER_UNIT, 2)                           AS NADAC_INGREDIENT_COST,
    ROUND((s.UNITS_REIMBURSED * n.NADAC_PER_UNIT)
          + (s.RX_COUNT * 10.50), 2)                                          AS PASS_THROUGH_BENCHMARK,
    ROUND(GREATEST(0,
          s.TOTAL_REIMBURSED
          - ((s.UNITS_REIMBURSED * n.NADAC_PER_UNIT) + (s.RX_COUNT * 10.50))
    ), 2)                                                                      AS ESTIMATED_SPREAD_DOLLARS,
    CASE
        WHEN REGEXP_LIKE(UPPER(s.PRODUCT_NAME),
             'OZEMPIC|WEGOVY|MOUNJARO|ZEPBOUND|TRULICITY|RYBELSUS|VICTOZA|SAXENDA|SEMAGLUTIDE|TIRZEPATIDE|DULAGLUTIDE|LIRAGLUTIDE')
             THEN 'GLP-1 & Weight/Diabetes'
        WHEN REGEXP_LIKE(UPPER(s.PRODUCT_NAME),
             'METFORMIN|JARDIANCE|FARXIGA|JANUVIA|INSULIN|LANTUS|HUMALOG|NOVOLOG|TRESIBA|GLIPIZIDE|EMPAGLIFLOZIN')
             THEN 'Type-2 Diabetes (Non-GLP-1)'
        WHEN REGEXP_LIKE(UPPER(s.PRODUCT_NAME),
             'ATORVASTATIN|ROSUVASTATIN|SIMVASTATIN|PRAVASTATIN|LOVASTATIN|LIPITOR|CRESTOR')
             THEN 'Statins / Cholesterol'
        WHEN REGEXP_LIKE(UPPER(s.PRODUCT_NAME),
             'LISINOPRIL|LOSARTAN|AMLODIPINE|METOPROLOL|HYDROCHLOROTHIAZIDE|VALSARTAN|CARVEDILOL|ENTRESTO|ELIQUIS|XARELTO')
             THEN 'Blood Pressure & Heart'
        WHEN REGEXP_LIKE(UPPER(s.PRODUCT_NAME),
             'ALBUTEROL|TRELEGY|SYMBICORT|ADVAIR|MONTELUKAST|BREO|SPIRIVA|FLUTICASONE')
             THEN 'Respiratory / Asthma'
        ELSE 'Other Therapeutic Classes'
    END                                                                        AS THERAPEUTIC_CLASS
FROM sdud_agg s
INNER JOIN RX_INTELLIGENCE.RAW.NADAC_LATEST n
    ON s.NDC11 = n.NDC;

-- ---------------------------------------------------------------------------
-- 2. V_I65_PARTD_PRESCRIBING
--    Medicare Part D prescribers (Louisville KY + Nashville TN) with metro
--    coordinates, brand/generic flag, and therapeutic class.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_I65_PARTD_PRESCRIBING AS
WITH base AS (
    SELECT
        PRSCRBR_NPI,
        PRSCRBR_LAST_ORG_NAME,
        PRSCRBR_FIRST_NAME,
        INITCAP(PRSCRBR_CITY)                       AS METRO_CITY,
        PRSCRBR_STATE_ABRVTN                         AS STATE,
        PRSCRBR_TYPE                                 AS SPECIALTY,
        BRND_NAME,
        GNRC_NAME,
        TOT_CLMS                                     AS PARTD_CLAIMS,
        TOT_30DAY_FILLS                              AS PARTD_30DAY_FILLS,
        TOT_DAY_SUPLY                                AS PARTD_DAY_SUPPLY,
        TOT_DRUG_CST                                 AS PARTD_DRUG_COST,
        TOT_BENES                                    AS PARTD_BENES
    FROM RX_INTELLIGENCE.RAW.PARTD_I65
    WHERE TOT_CLMS > 0
)
SELECT
    base.*,
    CASE WHEN UPPER(BRND_NAME) = UPPER(GNRC_NAME)
         THEN 'Generic' ELSE 'Brand' END            AS BRAND_GENERIC_FLAG,
    CASE WHEN UPPER(METRO_CITY) = 'LOUISVILLE' THEN 38.2527
         WHEN UPPER(METRO_CITY) = 'NASHVILLE'  THEN 36.1627 END AS LATITUDE,
    CASE WHEN UPPER(METRO_CITY) = 'LOUISVILLE' THEN -85.7585
         WHEN UPPER(METRO_CITY) = 'NASHVILLE'  THEN -86.7816 END AS LONGITUDE,
    CASE
        WHEN REGEXP_LIKE(UPPER(COALESCE(BRND_NAME, '') || ' ' || COALESCE(GNRC_NAME, '')),
             'OZEMPIC|WEGOVY|MOUNJARO|ZEPBOUND|TRULICITY|RYBELSUS|VICTOZA|SAXENDA|SEMAGLUTIDE|TIRZEPATIDE|DULAGLUTIDE|LIRAGLUTIDE')
             THEN 'GLP-1 & Weight/Diabetes'
        WHEN REGEXP_LIKE(UPPER(COALESCE(BRND_NAME, '') || ' ' || COALESCE(GNRC_NAME, '')),
             'METFORMIN|JARDIANCE|FARXIGA|JANUVIA|INSULIN|LANTUS|HUMALOG|NOVOLOG|TRESIBA|GLIPIZIDE|EMPAGLIFLOZIN')
             THEN 'Type-2 Diabetes (Non-GLP-1)'
        WHEN REGEXP_LIKE(UPPER(COALESCE(BRND_NAME, '') || ' ' || COALESCE(GNRC_NAME, '')),
             'ATORVASTATIN|ROSUVASTATIN|SIMVASTATIN|PRAVASTATIN|LOVASTATIN|LIPITOR|CRESTOR')
             THEN 'Statins / Cholesterol'
        WHEN REGEXP_LIKE(UPPER(COALESCE(BRND_NAME, '') || ' ' || COALESCE(GNRC_NAME, '')),
             'LISINOPRIL|LOSARTAN|AMLODIPINE|METOPROLOL|HYDROCHLOROTHIAZIDE|VALSARTAN|CARVEDILOL|ENTRESTO|ELIQUIS|XARELTO')
             THEN 'Blood Pressure & Heart'
        WHEN REGEXP_LIKE(UPPER(COALESCE(BRND_NAME, '') || ' ' || COALESCE(GNRC_NAME, '')),
             'ALBUTEROL|TRELEGY|SYMBICORT|ADVAIR|MONTELUKAST|BREO|SPIRIVA|FLUTICASONE')
             THEN 'Respiratory / Asthma'
        ELSE 'Other Therapeutic Classes'
    END                                             AS THERAPEUTIC_CLASS
FROM base;

-- ---------------------------------------------------------------------------
-- 3. SV_TRANSPARENT_RX — Cortex semantic view (GA: CREATE SEMANTIC VIEW)
--    Two logical tables: spread (Medicaid spread analysis) + partd (Part D).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE SEMANTIC VIEW SV_TRANSPARENT_RX
  TABLES (
    spread AS RX_INTELLIGENCE.ANALYTICS.V_KY_TN_SPREAD_ANALYSIS
      PRIMARY KEY (NDC11, STATE, YEAR, QUARTER)
      WITH SYNONYMS ('spread pricing', 'medicaid spread', 'spread leakage')
      COMMENT = 'KY/TN Medicaid spread-pricing analysis joined to the NADAC benchmark',
    partd AS RX_INTELLIGENCE.ANALYTICS.V_I65_PARTD_PRESCRIBING
      PRIMARY KEY (PRSCRBR_NPI, BRND_NAME, GNRC_NAME)
      WITH SYNONYMS ('medicare part d', 'prescriber', 'prescribing')
      COMMENT = 'Medicare Part D prescriber activity across the I-65 corridor'
  )
  FACTS (
    spread.total_reimbursed           AS spread.TOTAL_REIMBURSED
      COMMENT = 'Total Medicaid amount reimbursed',
    spread.nadac_ingredient_cost      AS spread.NADAC_INGREDIENT_COST
      COMMENT = 'NADAC benchmark ingredient cost (units x NADAC per unit)',
    spread.pass_through_benchmark     AS spread.PASS_THROUGH_BENCHMARK
      COMMENT = 'Pass-through benchmark (ingredient cost + $10.50 dispensing fee)',
    spread.estimated_spread_dollars   AS spread.ESTIMATED_SPREAD_DOLLARS
      COMMENT = 'Spread leakage above the pass-through benchmark',
    spread.rx_count                   AS spread.RX_COUNT
      COMMENT = 'Number of prescriptions',
    spread.units_reimbursed           AS spread.UNITS_REIMBURSED
      COMMENT = 'Number of units reimbursed',
    partd.partd_drug_cost             AS partd.PARTD_DRUG_COST
      COMMENT = 'Total drug cost (Medicare Part D)',
    partd.partd_claims                AS partd.PARTD_CLAIMS
      COMMENT = 'Total claims (Medicare Part D)',
    partd.partd_30day_fills           AS partd.PARTD_30DAY_FILLS
      COMMENT = 'Total 30-day fills (Medicare Part D)',
    partd.partd_day_supply            AS partd.PARTD_DAY_SUPPLY
      COMMENT = 'Total days supply (Medicare Part D)',
    partd.partd_benes                 AS partd.PARTD_BENES
      COMMENT = 'Total beneficiaries (Medicare Part D)'
  )
  DIMENSIONS (
    spread.state                       AS spread.STATE,
    spread.year                        AS spread.YEAR,
    spread.quarter                     AS spread.QUARTER,
    spread.drug_name                   AS spread.DRUG_NAME,
    spread.therapeutic_class           AS spread.THERAPEUTIC_CLASS,
    partd.metro_city                   AS partd.METRO_CITY,
    partd.state                        AS partd.STATE,
    partd.specialty                    AS partd.SPECIALTY,
    partd.brand_name                   AS partd.BRND_NAME,
    partd.generic_name                 AS partd.GNRC_NAME,
    partd.brand_generic_flag           AS partd.BRAND_GENERIC_FLAG
  )
  METRICS (
    spread.total_spread_leakage        AS SUM(spread.estimated_spread_dollars)
      COMMENT = 'Total spread leakage across KY/TN Medicaid',
    spread.total_medicaid_spend        AS SUM(spread.total_reimbursed)
      COMMENT = 'Total Medicaid reimbursement',
    spread.total_nadac_benchmark       AS SUM(spread.pass_through_benchmark)
      COMMENT = 'Total NADAC-based pass-through benchmark',
    spread.spread_per_claim            AS SUM(spread.estimated_spread_dollars) / NULLIF(SUM(spread.rx_count), 0)
      COMMENT = 'Average spread per prescription',
    partd.total_partd_drug_cost        AS SUM(partd.partd_drug_cost)
      COMMENT = 'Total Medicare Part D drug cost',
    partd.total_partd_claims           AS SUM(partd.partd_claims)
      COMMENT = 'Total Medicare Part D claims'
  )
  COMMENT = 'Transparent Rx: PBM spread-pricing transparency across the I-65 corridor';

-- ---------------------------------------------------------------------------
-- 4. Grants — least-privilege RX_APP_ROLE reads the analytics layer.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA RX_INTELLIGENCE.ANALYTICS TO ROLE RX_APP_ROLE;
GRANT SELECT ON VIEW RX_INTELLIGENCE.ANALYTICS.V_KY_TN_SPREAD_ANALYSIS TO ROLE RX_APP_ROLE;
GRANT SELECT ON VIEW RX_INTELLIGENCE.ANALYTICS.V_I65_PARTD_PRESCRIBING TO ROLE RX_APP_ROLE;
GRANT SELECT ON SEMANTIC VIEW RX_INTELLIGENCE.ANALYTICS.SV_TRANSPARENT_RX TO ROLE RX_APP_ROLE;
