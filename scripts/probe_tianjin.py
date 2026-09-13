# -*- coding: utf-8 -*-
"""tianjin 探: 用 ASCII 重命名 + read_shp 修复版"""
import os, sys, zipfile, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONUTF8", "1")

import geopandas as gpd

ROOT = Path("D:/Dev/situation/geonames")
VB = ROOT / "village-boundaries"
WORK = Path(os.environ.get("TEMP", "C:/Users/Administrator/AppData/Local/Temp")) / "vb_probe3"

z = VB / "village-boundaries-tianjin.zip"
if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir(parents=True)
with zipfile.ZipFile(z) as zf:
    zf.extractall(WORK)

# ASCII 重命名
shps = list(sorted(WORK.rglob("*.shp")))
for idx, shp in enumerate(shps):
    flat = WORK / f"shp_{idx:03d}"
    flat.mkdir(exist_ok=True)
    new_shp = flat / f"shp_{idx:03d}.shp"
    new_shp.write_bytes(shp.read_bytes())
    for side in shp.parent.iterdir():
        if side == shp:
            continue
        if side.stem == shp.stem:
            tgt = flat / (new_shp.stem + side.suffix)
            if side.is_file():
                tgt.write_bytes(side.read_bytes())

# 修复版 read_shp
for p in [flat / f"shp_{idx:03d}.shp"]:
    tries = ["UTF-8", "GBK"]
    last = None
    for e in tries:
        os.environ["SHAPE_ENCODING"] = e
        try:
            g = gpd.read_file(str(p), engine="fiona")
            print(f"read OK with enc={e}, rows={len(g)}, cols={list(g.columns)}")
            if "comname" in g.columns:
                for i in range(5):
                    print(f"  comname[{i}] = {g['comname'].iloc[i]!r}")
            break
        except (UnicodeDecodeError, UnicodeError):
            print(f"  {e} -> UnicodeDecodeError, skip")
            continue
        except Exception as ex:
            print(f"  {e} -> {type(ex).__name__}: {ex}")
            last = ex
