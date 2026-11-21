#!/usr/bin/env python3
"""
ingest_rx_data.py — Module A, Step 3 for the Transparent Rx Intelligence Workbench.

Pulls three ZERO-PHI public datasets and loads them into Snowflake RAW tables:
  1. RAW.SDUD_KY_TN      — CMS Medicaid State Drug Utilization 2025, KY+TN, unsuppressed
  2. RAW.NADAC_LATEST    — CMS NADAC 2026, latest weekly snapshot
  3. RAW.PARTD_I65       — CMS Medicare Part D Prescribers, Louisville KY + Nashville TN

Auth: key-pair (JWT), role ACCOUNTADMIN, warehouse RX_CORTEX_WH.
"""
import os
import re
import sys
import time

import requests
import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas

# ---------------------------------------------------------------------------
# Config (key-pair auth — reuses the RSA key already registered on this box)
# ---------------------------------------------------------------------------
ACCOUNT = "unpsrpt-il63479"
USER = "benjamin.atkinson@gmail.com"
ROLE = "ACCOUNTADMIN"
WAREHOUSE = "RX_CORTEX_WH"
DATABASE = "RX_INTELLIGENCE"
RAW_SCHEMA = "RAW"
PRIVATE_KEY_FILE = os.path.expanduser("~/.snowflake/rsa_key.p8")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SDUD_CSV = os.path.join(DATA_DIR, "sdud2025.csv")
NADAC_CSV = os.path.join(DATA_DIR, "nadac_2026.csv")
CMS_PARTD = "https://data.cms.gov/data-api/v1/dataset/d5aa71a8-dcc0-4570-8bcf-bd39deac69fe/data"

S = requests.Session()
S.headers.update({"User-Agent": "affirmedrx-demo/1.0", "Accept": "application/json"})


def normalize_ndc(x):
    """Strip all non-digits and zero-pad to exactly 11 characters."""
    return re.sub(r"\D", "", str(x)).zfill(11)


def to_num(s):
    """Coerce a possibly zero-padded string to float; None for blank."""
    s = str(s).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 1. Medicaid SDUD 2025 -> KY + TN, unsuppressed
# ---------------------------------------------------------------------------
def fetch_sdud_ky_tn():
    print("[1/3] Streaming SDUD 2025 CSV and filtering KY+TN unsuppressed ...", flush=True)
    chunks = []
    n_raw = 0
    for chunk in pd.read_csv(
        SDUD_CSV, chunksize=200_000, dtype=str, low_memory=False
    ):
        n_raw += len(chunk)
        mask = (chunk["State"].isin(["KY", "TN"])) & (chunk["Suppression Used"] == "false")
        c = chunk.loc[mask].copy()
        if not c.empty:
            chunks.append(c)
        if n_raw % 1_000_000 < 200_000:
            print(f"    ... scanned {n_raw:,} rows, kept {sum(len(x) for x in chunks):,}", flush=True)
    df = pd.concat(chunks, ignore_index=True)
    print(f"    scanned {n_raw:,} total rows; KY/TN unsuppressed kept {len(df):,}", flush=True)

    df["STATE"] = df["State"]
    df["UTILIZATION_TYPE"] = df["Utilization Type"]
    df["YEAR"] = pd.to_numeric(df["Year"], errors="coerce").fillna(0).astype("int64")
    df["QUARTER"] = pd.to_numeric(df["Quarter"], errors="coerce").fillna(0).astype("int64")
    df["NDC11"] = df["NDC"].map(normalize_ndc)
    df["PRODUCT_NAME"] = df["Product Name"].str.strip()
    df["UNITS_REIMBURSED"] = df["Units Reimbursed"].map(to_num)
    df["NUMBER_OF_PRESCRIPTIONS"] = df["Number of Prescriptions"].map(to_num)
    df["TOTAL_AMOUNT_REIMBURSED"] = df["Total Amount Reimbursed"].map(to_num)
    df["MEDICAID_AMOUNT_REIMBURSED"] = df["Medicaid Amount Reimbursed"].map(to_num)
    df["NON_MEDICAID_AMOUNT_REIMBURSED"] = df["Non Medicaid Amount Reimbursed"].map(to_num)

    cols = [
        "STATE", "UTILIZATION_TYPE", "YEAR", "QUARTER", "NDC11", "PRODUCT_NAME",
        "UNITS_REIMBURSED", "NUMBER_OF_PRESCRIPTIONS", "TOTAL_AMOUNT_REIMBURSED",
        "MEDICAID_AMOUNT_REIMBURSED", "NON_MEDICAID_AMOUNT_REIMBURSED",
    ]
    return df[cols]


# ---------------------------------------------------------------------------
# 2. CMS NADAC 2026 -> latest weekly snapshot
# ---------------------------------------------------------------------------
def fetch_latest_nadac():
    print("[2/3] Downloading NADAC 2026 CSV and selecting latest snapshot ...", flush=True)
    df = pd.read_csv(NADAC_CSV, dtype=str, low_memory=False)
    print(f"    raw NADAC rows: {len(df):,}", flush=True)

    df["AS_OF_DATE"] = pd.to_datetime(df["As of Date"], errors="coerce")
    latest = df["AS_OF_DATE"].max()
    print(f"    latest as_of_date: {latest.date()}", flush=True)
    df = df[df["AS_OF_DATE"] == latest].copy()

    df["NDC"] = df["NDC"].map(normalize_ndc)
    df["NDC_DESCRIPTION"] = df["NDC Description"].str.strip()
    df["NADAC_PER_UNIT"] = pd.to_numeric(df["NADAC Per Unit"], errors="coerce")
    df["EFFECTIVE_DATE"] = pd.to_datetime(df["Effective Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["AS_OF_DATE"] = df["AS_OF_DATE"].dt.strftime("%Y-%m-%d")
    df["PRICING_UNIT"] = df["Pricing Unit"]
    df["CLASSIFICATION_FOR_RATE_SETTING"] = df["Classification for Rate Setting"]

    df = df.dropna(subset=["NADAC_PER_UNIT"])
    df = df.drop_duplicates(subset=["NDC"], keep="first")
    cols = ["NDC", "NDC_DESCRIPTION", "NADAC_PER_UNIT", "EFFECTIVE_DATE",
            "AS_OF_DATE", "PRICING_UNIT", "CLASSIFICATION_FOR_RATE_SETTING"]
    print(f"    latest-snapshot rows after dedup: {len(df):,}", flush=True)
    return df[cols]


# ---------------------------------------------------------------------------
# 3. CMS Medicare Part D Prescribers -> Louisville KY + Nashville TN
# ---------------------------------------------------------------------------
def fetch_partd_city(city, state):
    """Fetch a representative sample for one metro. data.cms.gov clamps a single
    response to ~6,500 rows regardless of `size`, so one request = ~6,500 rows —
    ample for the demo's Part D prescriber example (full table is far larger)."""
    for attempt in range(7):
        try:
            r = S.get(
                CMS_PARTD,
                params={
                    f"filter[Prscrbr_State_Abrvtn]": state,
                    f"filter[Prscrbr_City]": city,
                    "size": 10000,
                    "offset": 0,
                },
                timeout=120,
            )
            if r.status_code == 429:
                wait = max(2 ** attempt, int(r.headers.get("Retry-After", 0) or 0))
                time.sleep(wait)
                continue
            r.raise_for_status()
            batch = r.json()
            if not isinstance(batch, list):
                raise RuntimeError(f"unexpected CMS response: {str(batch)[:200]}")
            return batch
        except requests.exceptions.HTTPError as e:
            if attempt == 6:
                raise
            time.sleep(2 ** attempt)
    return []


def fetch_partd_i65():
    print("[3/3] Fetching Medicare Part D prescribers (Louisville KY + Nashville TN) ...", flush=True)
    ky = fetch_partd_city("Louisville", "KY")
    print(f"    Louisville KY: {len(ky):,} rows (representative sample)", flush=True)
    time.sleep(2)
    tn = fetch_partd_city("Nashville", "TN")
    print(f"    Nashville TN: {len(tn):,} rows (representative sample)", flush=True)
    df = pd.DataFrame(ky + tn)
    if df.empty:
        raise RuntimeError("Part D fetch returned zero rows")

    df["PRSCRBR_NPI"] = df["Prscrbr_NPI"].astype(str)
    df["PRSCRBR_LAST_ORG_NAME"] = df["Prscrbr_Last_Org_Name"]
    df["PRSCRBR_FIRST_NAME"] = df["Prscrbr_First_Name"]
    df["PRSCRBR_CITY"] = df["Prscrbr_City"]
    df["PRSCRBR_STATE_ABRVTN"] = df["Prscrbr_State_Abrvtn"]
    df["PRSCRBR_TYPE"] = df["Prscrbr_Type"]
    df["BRND_NAME"] = df["Brnd_Name"]
    df["GNRC_NAME"] = df["Gnrc_Name"]
    df["TOT_CLMS"] = pd.to_numeric(df["Tot_Clms"], errors="coerce").fillna(0).astype("int64")
    df["TOT_30DAY_FILLS"] = pd.to_numeric(df["Tot_30day_Fills"], errors="coerce").fillna(0.0).astype("float64")
    df["TOT_DAY_SUPLY"] = pd.to_numeric(df["Tot_Day_Suply"], errors="coerce").fillna(0).astype("int64")
    df["TOT_DRUG_CST"] = pd.to_numeric(df["Tot_Drug_Cst"], errors="coerce").fillna(0.0).astype("float64")
    df["TOT_BENES"] = pd.to_numeric(df["Tot_Benes"], errors="coerce").fillna(0).astype("int64")

    df = df[df["TOT_CLMS"] > 0]
    cols = [
        "PRSCRBR_NPI", "PRSCRBR_LAST_ORG_NAME", "PRSCRBR_FIRST_NAME", "PRSCRBR_CITY",
        "PRSCRBR_STATE_ABRVTN", "PRSCRBR_TYPE", "BRND_NAME", "GNRC_NAME",
        "TOT_CLMS", "TOT_30DAY_FILLS", "TOT_DAY_SUPLY", "TOT_DRUG_CST", "TOT_BENES",
    ]
    return df[cols]


# ---------------------------------------------------------------------------
# Snowflake load
# ---------------------------------------------------------------------------
def get_conn():
    from cryptography.hazmat.primitives import serialization
    with open(PRIVATE_KEY_FILE, "rb") as f:
        pkey = serialization.load_pem_private_key(f.read(), password=None)
    return snowflake.connector.connect(
        account=ACCOUNT,
        user=USER,
        role=ROLE,
        warehouse=WAREHOUSE,
        database=DATABASE,
        private_key=pkey,
    )


RAW_DDL = {
    "SDUD_KY_TN": (
        "STATE VARCHAR, UTILIZATION_TYPE VARCHAR, YEAR NUMBER, QUARTER NUMBER, "
        "NDC11 VARCHAR(11), PRODUCT_NAME VARCHAR, UNITS_REIMBURSED NUMBER, "
        "NUMBER_OF_PRESCRIPTIONS NUMBER, TOTAL_AMOUNT_REIMBURSED NUMBER, "
        "MEDICAID_AMOUNT_REIMBURSED NUMBER, NON_MEDICAID_AMOUNT_REIMBURSED NUMBER"
    ),
    "NADAC_LATEST": (
        "NDC VARCHAR(11), NDC_DESCRIPTION VARCHAR, NADAC_PER_UNIT NUMBER, "
        "EFFECTIVE_DATE VARCHAR, AS_OF_DATE VARCHAR, PRICING_UNIT VARCHAR, "
        "CLASSIFICATION_FOR_RATE_SETTING VARCHAR"
    ),
    "PARTD_I65": (
        "PRSCRBR_NPI VARCHAR, PRSCRBR_LAST_ORG_NAME VARCHAR, PRSCRBR_FIRST_NAME VARCHAR, "
        "PRSCRBR_CITY VARCHAR, PRSCRBR_STATE_ABRVTN VARCHAR, PRSCRBR_TYPE VARCHAR, "
        "BRND_NAME VARCHAR, GNRC_NAME VARCHAR, TOT_CLMS NUMBER, TOT_30DAY_FILLS NUMBER, "
        "TOT_DAY_SUPLY NUMBER, TOT_DRUG_CST NUMBER, TOT_BENES NUMBER"
    ),
}


def load(conn, df, table):
    print(f"    writing {len(df):,} rows -> {DATABASE}.{RAW_SCHEMA}.{table} ...", flush=True)
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {DATABASE}.{RAW_SCHEMA}.{table}")
    cur.execute(f"CREATE TABLE {DATABASE}.{RAW_SCHEMA}.{table} ({RAW_DDL[table]})")
    success, nchunks, nrows, _ = write_pandas(
        conn, df, table_name=table, database=DATABASE, schema=RAW_SCHEMA,
        overwrite=False, quote_identifiers=False,
    )
    if not success:
        raise RuntimeError(f"write_pandas failed for {table}")
    print(f"    loaded {nrows:,} rows into {table}", flush=True)


def main():
    t0 = time.time()
    sdud = fetch_sdud_ky_tn()
    nadac = fetch_latest_nadac()
    partd = fetch_partd_i65()

    # ingestion thresholds (non-zero) per definition-of-done
    assert len(sdud) > 0, "SDUD KY/TN empty"
    assert len(nadac) > 0, "NADAC latest empty"
    assert len(partd) > 0, "Part D empty"
    print(f"\nTotals -> SDUD {len(sdud):,} | NADAC {len(nadac):,} | PARTD {len(partd):,}", flush=True)

    conn = get_conn()
    try:
        load(conn, sdud, "SDUD_KY_TN")
        load(conn, nadac, "NADAC_LATEST")
        load(conn, partd, "PARTD_I65")
    finally:
        conn.close()

    print(f"\nDONE in {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
