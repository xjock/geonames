# -*- coding: utf-8 -*-
"""regenerate _holes_summary.csv from actual _holes_XX.gpkg files."""
import os, csv, re
from pathlib import Path

os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr

VB = Path("D:/Dev/situation/geonames/village-boundaries")
SKIP = {65, 54, 15, 63, 81, 82}

rows = []
for f in sorted(VB.glob("_holes_*.gpkg")):
    m = re.match(r"_holes_(\d+)_([^.]+)\.gpkg", f.name)
    if not m:
        continue
    code = int(m.group(1))
    name = m.group(2)
    if code in SKIP:
        continue
    ds = ogr.Open(str(f))
    lyr = ds.GetLayer(0)
    n_feat = lyr.GetFeatureCount()
    total_area = 0.0
    lyr.ResetReading()
    for feat in lyr:
        total_area += feat.GetField("area_deg2") or 0.0
    sz = f.stat().st_size / 1024 / 1024
    rows.append({
        "adcode": code * 10000,
        "name": name,
        "n_holes": n_feat,
        "hole_area_deg2": round(total_area, 4),
        "size_mb": round(sz, 2),
        "el_s": 0.0,
    })
    ds = None

with open(VB / "_holes_summary.csv", "w", encoding="utf-8", newline="") as out:
    w = csv.DictWriter(out, fieldnames=["adcode","name","n_holes","hole_area_deg2","size_mb","el_s"])
    w.writeheader()
    for r in sorted(rows, key=lambda x: -x["hole_area_deg2"]):
        w.writerow(r)
print(f"wrote {len(rows)} rows")
for r in sorted(rows, key=lambda x: -x["hole_area_deg2"]):
    print(f"  {r['adcode']:06d} {r['name']:8s} n={r['n_holes']:5d} area={r['hole_area_deg2']:.4f} {r['size_mb']}MB")