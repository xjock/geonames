# -*- coding: utf-8 -*-
"""只 fix chongqing + hunan: 读当前 gpkg → 移除这2 省 → 重新处理这2 省 → 合并写回"""
import os, sys, io, shutil, zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from update_full_village_gpkg import (
    read_shp, normalize, load_codes, extract_all
)

VB = ROOT / "village-boundaries"
GPKG = VB / "cn_villages_named.gpkg"
CSV = VB / "cn_villages_named.csv"
TMP_GPKG = VB / "cn_villages_named_v7.gpkg"
TMP_CSV = VB / "cn_villages_named_v7.csv"
WORK = Path(os.environ.get("TEMP", "C:/Users/Administrator/AppData/Local/Temp")) / "vb_fix2"

PROVS = ["chongqing", "hunan"]

def main():
    print(f"loading current gpkg...", flush=True)
    cur = gpd.read_file(str(GPKG), layer="villages")
    print(f"current rows: {len(cur):,}", flush=True)

    print(f"dropping rows for {PROVS}...", flush=True)
    keep = cur[~cur["src_province"].isin(PROVS)].copy()
    print(f"kept: {len(keep):,}", flush=True)
    del cur

    print(f"\nre-processing {PROVS}...", flush=True)
    codes = load_codes()
    new_parts = []
    for prov in PROVS:
        z = VB / f"village-boundaries-{prov}.zip"
        tmp = WORK / prov
        shps = extract_all(z, tmp)
        for shp, layer in shps:
            try:
                g, enc = read_shp(shp)
                if g.empty: continue
                sub, code_col, name_col = normalize(g, codes, prov, layer, enc)
                new_parts.append(sub)
                miss = int((sub["official_name"] == "").sum())
                print(f"  {prov:10s} {layer[:35]:35s} rows={len(sub):>5d} "
                      f"code={code_col or '-':10s} name={name_col or '-'}", flush=True)
            except Exception as ex:
                print(f"  FAIL {prov}/{layer}: {ex}", flush=True)

    if not new_parts:
        sys.exit("nothing new")

    print(f"\nconcat {len(new_parts)} new parts + keep...", flush=True)
    new = pd.concat(new_parts, ignore_index=True)
    cq_n = sum(new['src_province']=='chongqing')
    hn_n = sum(new['src_province']=='hunan')
    print(f"new rows: {len(new):,}", flush=True)
    print(f"  chongqing rows: {cq_n}", flush=True)
    print(f"  hunan rows: {hn_n}", flush=True)
    print(f"  chongqing sample names: {new[new['src_province']=='chongqing']['shp_name'].head(3).tolist()}", flush=True)
    print(f"  hunan sample codes: {new[new['src_province']=='hunan']['code12'].head(3).tolist()}", flush=True)
    hn_off = (new[new['src_province']=='hunan']['official_name']!='').sum()
    print(f"  hunan off_hit: {hn_off}/{hn_n}", flush=True)

    final = pd.concat([keep, new], ignore_index=True)
    final = gpd.GeoDataFrame(final, crs="EPSG:4326")
    print(f"final rows: {len(final):,}", flush=True)

    print(f"\nwriting {TMP_GPKG.name}...", flush=True)
    final.to_file(str(TMP_GPKG), driver="GPKG", layer="villages")
    final.drop(columns="geometry").to_csv(str(TMP_CSV), index=False, encoding="utf-8")
    print(f"DONE: {len(final):,} rows -> {TMP_GPKG.name}", flush=True)

if __name__ == "__main__":
    main()