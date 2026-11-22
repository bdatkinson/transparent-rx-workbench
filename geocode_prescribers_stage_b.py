"""Stage B: geocode prescriber addresses via Census batch geocoder.

Loads prescriber_addresses.json (KY/TN only), batch-geocodes, falls back to
zip-centroid for No_Match, writes prescriber_geo.json {npi: {lat, lon, ...}}.
"""
import csv
import io
import json
import subprocess
import urllib.request


def main():
    d = json.load(open("/home/batkinson/affirmedrx-snowflake-demo/prescriber_addresses.json"))
    d = {n: g for n, g in d.items() if g["state"] in ("KY", "TN")}
    print(f"KY/TN prescribers: {len(d)}")

    # build input CSV (id, street, city, state, zip)
    with open("/tmp/addrs.csv", "w", newline="") as f:
        w = csv.writer(f)
        for npi, g in d.items():
            w.writerow([npi, g["street"], g["city"], g["state"], g["zip"]])

    r = subprocess.run(
        ["curl", "-s", "--max-time", "180",
         "-F", "addressFile=@/tmp/addrs.csv",
         "-F", "benchmark=4",
         "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout:
        print("Census batch FAILED:", r.stderr[:500])
        return

    geo = {}
    no_match = []
    for row in csv.reader(io.StringIO(r.stdout)):
        if not row:
            continue
        npi = row[0]
        if len(row) >= 3 and row[2] == "Match" and len(row) >= 6:
            lon, lat = row[5].split(",")
            geo[npi] = {
                "lat": float(lat), "lon": float(lon),
                "matched_address": row[4],
                "name": d.get(npi, {}).get("name", ""),
                "city": d.get(npi, {}).get("city", ""),
                "state": d.get(npi, {}).get("state", ""),
                "zip": d.get(npi, {}).get("zip", ""),
                "precision": "street",
            }
        else:
            no_match.append(npi)

    print(f"matched (street): {len(geo)} | no_match: {len(no_match)}")

    # zip-centroid fallback for No_Match
    for npi in no_match:
        zc = d.get(npi, {}).get("zip", "")
        if not zc:
            continue
        try:
            url = ("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
                   f"?address={zc}&benchmark=4&format=json")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                j = json.load(resp)
            m = (j.get("result", {}).get("addressMatches") or [{}])[0]
            coords = m.get("coordinates", {})
            if coords:
                geo[npi] = {
                    "lat": coords["y"], "lon": coords["x"],
                    "matched_address": f"{zc} (ZIP centroid)",
                    "name": d.get(npi, {}).get("name", ""),
                    "city": d.get(npi, {}).get("city", ""),
                    "state": d.get(npi, {}).get("state", ""),
                    "zip": zc,
                    "precision": "zip",
                }
        except Exception as e:
            print(f"  zip fallback failed for {npi} ({zc}): {e}")

    print(f"total geocoded: {len(geo)} (street={sum(1 for g in geo.values() if g['precision']=='street')}, "
          f"zip={sum(1 for g in geo.values() if g['precision']=='zip')})")
    print(f"still unmatched: {len([n for n in no_match if n not in geo])}")

    with open("/home/batkinson/affirmedrx-snowflake-demo/prescriber_geo.json", "w") as f:
        json.dump(geo, f, indent=1)
    print("saved prescriber_geo.json")


if __name__ == "__main__":
    main()
