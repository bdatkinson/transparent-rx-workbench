"""Stage A: pull unique prescribers, look up practice addresses via NPPES API.

NPPES `number` param does NOT batch (comma-separated errors out; repeated params
only honor the first). So we hit the endpoint once per NPI, sequentially, with a
small sleep + retry. Writes prescriber_addresses.json incrementally so a timeout
resumes cleanly.
"""
import json
import os
import time
import urllib.request

import snowflake.connector
from cryptography.hazmat.primitives.serialization import load_pem_private_key

OUT = "/home/batkinson/affirmedrx-snowflake-demo/prescriber_addresses.json"

# 1. Snowflake: distinct NPIs
k = load_pem_private_key(open("/home/batkinson/.snowflake/rsa_key.p8", "rb").read(), password=None)
conn = snowflake.connector.connect(
    account="unpsrpt-il63479", user="benjamin.atkinson@gmail.com",
    role="ACCOUNTADMIN", warehouse="RX_CORTEX_WH", private_key=k, login_timeout=30,
)
cur = conn.cursor()
cur.execute(
    "SELECT DISTINCT PRSCRBR_NPI FROM RX_INTELLIGENCE.ANALYTICS.V_I65_PARTD_PRESCRIBING ORDER BY 1"
)
npis = [str(r[0]) for r in cur.fetchall()]
print(f"distinct NPIs: {len(npis)}")

# resume from any prior partial save
geo = {}
if os.path.exists(OUT):
    with open(OUT) as f:
        geo = json.load(f)
    print(f"resuming with {len(geo)} already saved")


def lookup(npi):
    url = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number=" + npi
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.load(r)
    res = data.get("results") or []
    if not res:
        return None
    r = res[0]
    addrs = r.get("addresses", [])
    loc = next((a for a in addrs if a.get("address_purpose") == "LOCATION"), addrs[0] if addrs else None)
    if not loc:
        return None
    street = " ".join(filter(None, [loc.get("address_1", ""), loc.get("address_2", "")])).strip()
    b = r.get("basic", {})
    return {
        "street": street,
        "city": (loc.get("city", "") or "").strip(),
        "state": (loc.get("state", "") or "").strip(),
        "zip": (loc.get("postal_code", "") or "").strip()[:5],
        "name": f"{b.get('first_name', '')} {b.get('last_name', '')}".strip(),
    }


done = skipped = failed = 0
todo = [n for n in npis if n not in geo]
print(f"to fetch: {len(todo)}")
for i, npi in enumerate(todo, 1):
    got = None
    for attempt in range(4):
        try:
            got = lookup(npi)
            if got is not None:
                break
            got = None  # empty results, treat as no-address
            break
        except Exception as e:
            time.sleep(2 * (attempt + 1))
            if attempt == 3:
                print(f"  !! {npi} failed: {e}")
    if got:
        geo[npi] = got
        done += 1
    else:
        skipped += 1
    time.sleep(0.15)
    if i % 50 == 0 or i == len(todo):
        with open(OUT, "w") as f:
            json.dump(geo, f, indent=1)
        print(f"  {i}/{len(todo)} done={done} skipped={skipped} total_saved={len(geo)}")

print(f"FINAL: saved {len(geo)} addresses, skipped {skipped} (no NPPES address)")
