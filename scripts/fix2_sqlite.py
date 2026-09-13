# -*- coding: utf-8 -*-
"""fix chongqing + hunan in-place via sqlite3 + ogr2ogr (避免加载 9GB gpkg 到内存)"""
import os, sys, subprocess, zipfile, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONUTF8", "1")

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from update_full_village_gpkg import read_shp, normalize, load_codes, extract_all

VB = ROOT / "village-boundaries"
GPKG = VB / "cn_villages_named.gpkg"
TMP_GPKG = VB / "_fix2_new.gpkg"
TMP_CSV = VB / "_fix2_new.csv"
WORK = Path(os.environ.get("TEMP")) / "vb_fix2_sqlite"
PROVS = ["chongqing", "hunan"]
SQLITE = Path("D:/Dev/toolchain/libmapping-1.0.0/bin/sqlite3.exe")
OGR2OGR = Path("D:/Dev/toolchain/libmapping-1.0.0/bin/ogr2ogr.exe")


def main():
    print(f"[1] process {PROVS} zips...", flush=True)
    codes = load_codes()
    parts = []
    for prov in PROVS:
        z = VB / f"village-boundaries-{prov}.zip"
        tmp = WORK / prov
        shps = extract_all(z, tmp)
        for shp, layer in shps:
            try:
                g, enc = read_shp(shp)
                if g.empty: continue
                sub, code_col, name_col = normalize(g, codes, prov, layer, enc)
                parts.append(sub)
                print(f"  {prov:10s} {layer[:35]:35s} rows={len(sub):>5d} "
                      f"code={code_col or '-':10s} name={name_col or '-'}", flush=True)
            except Exception as ex:
                print(f"  FAIL: {ex}", flush=True)
    new = pd.concat(parts, ignore_index=True)
    new = gpd.GeoDataFrame(new, crs="EPSG:4326")
    print(f"  new rows: {len(new):,}", flush=True)

    print(f"\n[2] write {TMP_GPKG.name}...", flush=True)
    new.to_file(str(TMP_GPKG), driver="GPKG", layer="villages")
    new.drop(columns="geometry").to_csv(str(TMP_CSV), index=False, encoding="utf-8")
    print(f"  done: {len(new):,} rows", flush=True)

    print(f"\n[3] DELETE old rows from main gpkg...", flush=True)
    sql = f"DELETE FROM villages WHERE src_province IN ('{PROVS[0]}','{PROVS[1]}');"
    print(f"  sql: {sql}", flush=True)
    r = subprocess.run(
        [str(SQLITE), str(GPKG), sql],
        capture_output=True, text=True
    )
    print(f"  stdout: {r.stdout}", flush=True)
    if r.returncode != 0:
        print(f"  stderr: {r.stderr}", flush=True)
        sys.exit("sqlite DELETE failed")

    print(f"\n[4] ogr2ogr -append new rows...", flush=True)
    r = subprocess.run([
        str(OGR2OGR), "-f", "GPKG", "-append", "-nln", "villages",
        str(GPKG), str(TMP_GPKG)
    ], capture_output=True, text=True)
    print(f"  rc: {r.returncode}", flush=True)
    if r.returncode != 0:
        print(f"  stderr: {r.stderr[:500]}", flush=True)
        sys.exit("ogr2ogr append failed")

    print(f"\n[5] cleanup tmp...", flush=True)
    TMP_GPKG.unlink()
    TMP_CSV.unlink()

    print(f"\n[6] verify count...", flush=True)
    r = subprocess.run(
        [str(SQLITE), str(GPKG), "SELECT src_province, COUNT(*) FROM villages GROUP BY src_province;"],
        capture_output=True, text=True
    )
    print(r.stdout, flush=True)
    if r.returncode != 0:
        print(r.stderr, flush=True)

if __name__ == "__main__":
    main()