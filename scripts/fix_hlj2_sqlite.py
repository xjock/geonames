# -*- coding: utf-8 -*-
"""hlj fallback fix in-place via sqlite3 + ogr2ogr"""
import os, sys, subprocess
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
TMP_GPKG = VB / "_fix_hlj2.gpkg"
TMP_CSV = VB / "_fix_hlj2.csv"
WORK = Path(os.environ.get("TEMP", "C:/Users/Administrator/AppData/Local/Temp")) / "vb_fix_hlj2"
SQLITE = Path("D:/Dev/toolchain/libmapping-1.0.0/bin/sqlite3.exe")
OGR2OGR = Path("D:/Dev/toolchain/libmapping-1.0.0/bin/ogr2ogr.exe")
PROV = "heilongjiang"


def main():
    print(f"[1] process {PROV}...", flush=True)
    codes = load_codes()
    z = VB / f"village-boundaries-{PROV}.zip"
    shps = extract_all(z, WORK)
    parts = []
    for shp, layer in shps:
        try:
            g, enc = read_shp(shp)
            if g.empty: continue
            sub, code_col, name_col = normalize(g, codes, PROV, layer, enc)
            parts.append(sub)
            empty = int((sub["shp_name"].astype(str).str.strip() == "").sum())
            print(f"  {layer[:35]:35s} rows={len(sub):>5d} empty={empty:>3d} "
                  f"code={code_col or '-':10s} name={name_col or '-'}", flush=True)
        except Exception as ex:
            print(f"  FAIL: {ex}", flush=True)
    new = pd.concat(parts, ignore_index=True)
    new = gpd.GeoDataFrame(new, crs="EPSG:4326")
    print(f"  new total rows: {len(new):,}", flush=True)
    print(f"  new empty: {int((new['shp_name'].astype(str).str.strip()=='').sum())}", flush=True)

    print(f"\n[2] write {TMP_GPKG.name}...", flush=True)
    new.to_file(str(TMP_GPKG), driver="GPKG", layer="villages")
    new.drop(columns="geometry").to_csv(str(TMP_CSV), index=False, encoding="utf-8")

    print(f"\n[3] DELETE old hlj rows...", flush=True)
    sql = f"DELETE FROM villages WHERE src_province='{PROV}';"
    r = subprocess.run([str(SQLITE), str(GPKG), sql], capture_output=True, text=True)
    print(f"  rc={r.returncode}", flush=True)
    if r.returncode != 0:
        print(r.stderr[:500]); sys.exit("delete failed")

    print(f"\n[4] ogr2ogr append...", flush=True)
    r = subprocess.run([
        str(OGR2OGR), "-f", "GPKG", "-append", "-nln", "villages",
        str(GPKG), str(TMP_GPKG)
    ], capture_output=True, text=True)
    print(f"  rc={r.returncode}", flush=True)
    if r.returncode != 0:
        print(r.stderr[:500]); sys.exit("append failed")

    TMP_GPKG.unlink()
    TMP_CSV.unlink()

    print(f"\n[5] verify...", flush=True)
    r = subprocess.run([str(SQLITE), str(GPKG),
        f"SELECT COUNT(*) AS hlj_total, "
        f"SUM(CASE WHEN length(shp_name)=0 THEN 1 ELSE 0 END) AS hlj_empty "
        f"FROM villages WHERE src_province='{PROV}';"],
        capture_output=True, text=True)
    print(r.stdout, flush=True)

    r = subprocess.run([str(SQLITE), str(GPKG),
        "SELECT src_province, COUNT(*) AS total, "
        "SUM(CASE WHEN length(shp_name)=0 THEN 1 ELSE 0 END) AS empty "
        "FROM villages GROUP BY src_province ORDER BY empty DESC LIMIT 20;"],
        capture_output=True, text=True)
    print(r.stdout, flush=True)


if __name__ == "__main__":
    main()
