"""Stage C: load prescriber_geo.json into Snowflake RAW.PRESCRIBER_GEO."""
import json

import snowflake.connector
from cryptography.hazmat.primitives.serialization import load_pem_private_key

k = load_pem_private_key(open("/home/batkinson/.snowflake/rsa_key.p8", "rb").read(), password=None)
conn = snowflake.connector.connect(
    account="unpsrpt-il63479", user="benjamin.atkinson@gmail.com",
    role="ACCOUNTADMIN", warehouse="RX_CORTEX_WH", private_key=k, login_timeout=30,
)
cur = conn.cursor()

cur.execute("""
CREATE OR REPLACE TABLE RX_INTELLIGENCE.RAW.PRESCRIBER_GEO (
    PRSCRBR_NPI VARCHAR(10),
    NAME         VARCHAR(200),
    ADDRESS      VARCHAR(500),
    CITY         VARCHAR(100),
    STATE        VARCHAR(2),
    ZIP          VARCHAR(10),
    LATITUDE     FLOAT,
    LONGITUDE    FLOAT,
    PRECISION    VARCHAR(20)
)
""")

geo = json.load(open("/home/batkinson/affirmedrx-snowflake-demo/prescriber_geo.json"))
rows = [
    (npi, g["name"], g["matched_address"], g["city"], g["state"],
     g["zip"], g["lat"], g["lon"], g["precision"])
    for npi, g in geo.items()
]
cur.executemany(
    "INSERT INTO RX_INTELLIGENCE.RAW.PRESCRIBER_GEO "
    "(PRSCRBR_NPI, NAME, ADDRESS, CITY, STATE, ZIP, LATITUDE, LONGITUDE, PRECISION) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
    rows,
)

cur.execute("SELECT COUNT(*), SUM(CASE WHEN PRECISION='street' THEN 1 ELSE 0 END) FROM RX_INTELLIGENCE.RAW.PRESCRIBER_GEO")
total, street = cur.fetchone()
print(f"loaded {total} rows (street={street}, zip={total - street})")

# sanity: coordinate spread (should be I-65 corridor, lat ~36-38.5, lon ~-86.5..-85.5)
cur.execute("SELECT MIN(LATITUDE), MAX(LATITUDE), MIN(LONGITUDE), MAX(LONGITUDE) FROM RX_INTELLIGENCE.RAW.PRESCRIBER_GEO")
mn_lat, mx_lat, mn_lon, mx_lon = cur.fetchone()
print(f"lat range {mn_lat:.3f}..{mx_lat:.3f}  lon range {mn_lon:.3f}..{mx_lon:.3f}")
