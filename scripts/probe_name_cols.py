# -*- coding: utf-8 -*-
"""探测 4 省 shp 村级名识别结果,不写 gpkg,RAM 极低。
输出 hubei/hunan/xinjiang/tianjin 的 name_col + 样本行。
"""
import os, sys, io, zipfile, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import geopandas as gpd

ROOT = Path("D:/Dev/situation/geonames")
VB = ROOT / "village-boundaries"
WORK = Path(os.environ.get("TEMP", "C:/Users/Administrator/AppData/Local/Temp")) / "vb_probe"
PROBES = ["hubei", "hunan", "xinjiang", "tianjin"]

NAME_COLS_BEST = ["CJDCQMC", "CJGZQYMC", "CUNMC", "CJMC", "CJNAME",
                  "CUN_NAME", "CUN_MC", "cun_name", "cunmc",
                  "comname", "comname_1", "BLOCK_NAME", "BLOCKNAME",
                  "village_name", "村名", "村名称", "村名_1"]
NAME_COLS_OK = ["XZQMC", "DJZQMC", "xzqmc", "name", "NAME", "MC", "QMC",
                "QMC_1", "XZQMC_1", "XZQMC_2", "cname"]
NAME_COLS_LAST = ["XZXZQMC", "XJXZQMC", "SJXZQMC", "SJGZQYMC", "DSJGZQYMC",
                  "QXJGZQYMC", "XZJGZQYMC", "sheng_name", "shi_name",
                  "xian_name", "xiang_name", "county_name", "town_name"]


def extract_all(z, dst):
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(dst)
    return list(sorted(dst.rglob("*.shp")))


def find_name(gdf, exclude):
    cols = [c for c in gdf.columns
            if c != exclude and gdf[c].dtype.kind in ("O", "U", "S")]
    if not cols:
        cols = [c for c in gdf.columns if c != exclude]
    norm = {c.upper().strip(): c for c in cols}
    for pri in (NAME_COLS_BEST, NAME_COLS_OK, NAME_COLS_LAST):
        for cand in pri:
            c = norm.get(cand.upper())
            if c:
                return c, pri[0]
        for cand in pri:
            cl = cand.lower()
            for c in cols:
                if cl in c.lower():
                    return c, pri[0]
    return None, None


def main():
    for prov in PROBES:
        z = VB / f"village-boundaries-{prov}.zip"
        if not z.exists():
            print(f"SKIP {prov}: zip not found")
            continue
        tmp = WORK / prov
        shps = extract_all(z, tmp)
        print(f"\n=== {prov} ({len(shps)} shp) ===")
        for shp in shps:
            stem = shp.stem[:50]
            try:
                cpg = shp.with_suffix(".cpg")
                declared = None
                if cpg.exists():
                    declared = cpg.read_text(encoding="ascii", errors="ignore").strip() or None
                # 用 fix 过的 read_shp (支持 GBK-misdecode 检测)
                import sys as _sys
                _sys.path.insert(0, str(Path(__file__).resolve().parent))
                from update_full_village_gpkg import read_shp
                gdf, used_enc = read_shp(shp)
                if gdf is None:
                    print(f"  {stem}: read FAIL")
                    continue
                if gdf.empty:
                    print(f"  {stem}: EMPTY")
                    continue
                name_col, pri = find_name(gdf, None)
                sample = ""
                if name_col:
                    vals = gdf[name_col].dropna().astype(str).head(3).tolist()
                    sample = "|".join(vals)[:80]
                print(f"  {stem:50s} enc={used_enc:5s} rows={len(gdf):>5d} "
                      f"name_col={name_col!s:20s} (pri={pri}) sample={sample}")
            except Exception as ex:
                print(f"  {stem}: ERR {type(ex).__name__}: {str(ex)[:60]}")


if __name__ == "__main__":
    main()
