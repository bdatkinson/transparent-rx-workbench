"""Stage B (fallback): fill No_Match prescribers with zip-centroid coordinates.

Uses zippopotam.us (free, no key) per unique zip, labels precision="zip".
Merges into prescriber_geo.json.
"""
import json
import time
import urllib.request


def main():
    base = "/home/batkinson/affirmedrx-snowflake-demo/"
    addr = json.load(open(base + "prescriber_addresses.json"))
    addr = {n: g for n, g in addr.items() if g["state"] in ("KY", "TN")}
    geo = json.load(open(base + "prescriber_geo.json"))

    missing = [n for n in addr if n not in geo]
    print(f"no-match to fill: {len(missing)}")

    zips = sorted({addr[n]["zip"] for n in missing if addr[n].get("zip")})
    print(f"unique zips: {len(zips)}")

    zip_coords = {}
    for zc in zips:
        try:
            url = f"https://api.zippopotam.us/us/{zc}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.load(r)
            p = j["places"][0]
            zip_coords[zc] = (float(p["latitude"]), float(p["longitude"]))
            print(f"  {zc} -> {zip_coords[zc]}")
        except Exception as e:
            print(f"  {zc} FAILED: {e}")
        time.sleep(0.3)

    added = 0
    for n in missing:
        g = addr[n]
        zc = g.get("zip", "")
        if zc in zip_coords:
            lat, lon = zip_coords[zc]
            geo[n] = {
                "lat": lat, "lon": lon,
                "matched_address": f"{zc} (ZIP centroid)",
                "name": g.get("name", ""),
                "city": g.get("city", ""),
                "state": g.get("state", ""),
                "zip": zc,
                "precision": "zip",
            }
            added += 1

    print(f"added {added} zip-centroid prescribers; total now {len(geo)}")
    street = sum(1 for g in geo.values() if g["precision"] == "street")
    zipc = sum(1 for g in geo.values() if g["precision"] == "zip")
    print(f"street={street} zip={zipc}")

    with open(base + "prescriber_geo.json", "w") as f:
        json.dump(geo, f, indent=1)
    print("saved prescriber_geo.json")


if __name__ == "__main__":
    main()
