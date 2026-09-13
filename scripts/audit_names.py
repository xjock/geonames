# -*- coding: utf-8 -*-
"""审计 gpkg: 每省 name_col + shp_name 样本 + 行政区级误用 + 空值"""
import os, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONUTF8", "1")

import geopandas as gpd

GPKG = Path("D:/Dev/situation/geonames/village-boundaries/cn_villages_named.gpkg")
g = gpd.read_file(str(GPKG), layer="villages")
print(f"total rows: {len(g):,}")

print("\n=== per-province ===")
print(f"{'prov':12s} {'rows':>7s} {'shp_nonempty':>14s} {'off_hit':>9s} sample")
for prov, sub in g.groupby("src_province"):
    n = len(sub)
    ne = sum(1 for v in sub["shp_name"].astype(str) if v and v != "nan")
    hit = sum(1 for v in sub["official_name"].astype(str) if v and v != "nan")
    sample = sub["shp_name"].dropna().astype(str)
    sample = sample[sample.str.len() > 0].head(3).tolist()
    print(f"{prov:12s} {n:>7d} {ne:>7d}/{n:<5d} {hit:>5d}/{n:<3d} {' | '.join(sample)[:80]}")

print("\n=== shp_name ending w/ 行政区级 (省/市/县/区/乡/镇/街道) ===")
susp = g["shp_name"].astype(str)
ends_bad = susp.str.endswith(("省", "市", "县", "区", "乡", "镇", "街道", "盟", "州"))
print(f"total bad-ending: {ends_bad.sum():,}")
for prov, sub in g[ends_bad].groupby("src_province"):
    sample = sub["shp_name"].astype(str).head(3).tolist()
    print(f"  {prov}: {len(sub):>6d}  {' | '.join(sample)[:80]}")

print("\n=== empty shp_name ===")
empty = g["shp_name"].isna() | (g["shp_name"].astype(str).str.strip() == "") | (g["shp_name"].astype(str) == "nan")
print(f"total empty: {empty.sum():,}")
for prov, sub in g[empty].groupby("src_province"):
    print(f"  {prov}: {len(sub):>6d}")
