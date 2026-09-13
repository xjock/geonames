# -*- coding: utf-8 -*-
"""tianjin comname 解码链测试: GBK→latin1→UTF-8 三次错位反转"""
import os, sys, zipfile, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import geopandas as gpd

ROOT = Path("D:/Dev/situation/geonames")
VB = ROOT / "village-boundaries"
WORK = Path(os.environ.get("TEMP", "C:/Users/Administrator/AppData/Local/Temp")) / "vb_probe4"

z = VB / "village-boundaries-tianjin.zip"
if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir(parents=True)
with zipfile.ZipFile(z) as zf:
    zf.extractall(WORK)
shps = list(sorted(WORK.rglob("*.shp")))
for idx, shp in enumerate(shps):
    flat = WORK / f"shp_{idx:03d}"
    flat.mkdir(exist_ok=True)
    new_shp = flat / f"shp_{idx:03d}.shp"
    new_shp.write_bytes(shp.read_bytes())
    for side in shp.parent.iterdir():
        if side == shp: continue
        if side.stem == shp.stem and side.is_file():
            (flat / (new_shp.stem + side.suffix)).write_bytes(side.read_bytes())

p = flat / f"shp_{idx:03d}.shp"
os.environ["SHAPE_ENCODING"] = "GBK"
g = gpd.read_file(str(p), engine="fiona")

print("== chain A: str.encode('latin1').decode('gbk') ==")
for i in range(5):
    v = g['comname'].iloc[i]
    try:
        print(f"  [{i}] = {v.encode('latin1').decode('gbk')}")
    except Exception as ex:
        print(f"  [{i}] FAIL: {ex}")

print("\n== chain B: str.encode('utf-8','replace').decode('gbk','replace') ==")
for i in range(5):
    v = g['comname'].iloc[i]
    try:
        print(f"  [{i}] = {v.encode('utf-8','replace').decode('gbk','replace')}")
    except Exception as ex:
        print(f"  [{i}] FAIL: {ex}")

print("\n== chain C: str.encode('latin1').decode('utf-8','replace').encode('latin1').decode('gbk') ==")
for i in range(5):
    v = g['comname'].iloc[i]
    try:
        a = v.encode('latin1').decode('utf-8', 'replace')
        b = a.encode('latin1').decode('gbk', 'replace')
        print(f"  [{i}] = {b}")
    except Exception as ex:
        print(f"  [{i}] FAIL: {ex}")
