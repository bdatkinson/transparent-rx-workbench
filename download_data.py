#!/usr/bin/env python3
"""Download the two medicaid CSVs to disk with progress, so ingestion can resume/process locally."""
import os, time, requests

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA, exist_ok=True)

FILES = {
    "sdud2025.csv": "https://download.medicaid.gov/data/sdud2025_updatedjuly2026.csv",
    "nadac_2026.csv": "https://download.medicaid.gov/data/nadac-national-average-drug-acquisition-cost-11-18-2026.csv",
}

S = requests.Session()
S.headers.update({"User-Agent": "affirmedrx-demo/1.0"})

for name, url in FILES.items():
    path = os.path.join(DATA, name)
    if os.path.exists(path) and os.path.getsize(path) > 10_000_000:
        print(f"[skip] {name} already present ({os.path.getsize(path)/1e6:.1f} MB)", flush=True)
        continue
    print(f"[dl] {name} <- {url}", flush=True)
    t0 = time.time()
    with S.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0)) or 0
        done = 0
        with open(path + ".part", "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"    {name}: {done/1e6:.1f}/{total/1e6:.1f} MB ({done/total*100:.0f}%)", flush=True)
                else:
                    print(f"    {name}: {done/1e6:.1f} MB", flush=True)
    os.replace(path + ".part", path)
    print(f"[ok] {name} {os.path.getsize(path)/1e6:.1f} MB in {time.time()-t0:.0f}s", flush=True)

print("ALL DOWNLOADS COMPLETE", flush=True)
