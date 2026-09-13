# -*- coding: utf-8 -*-
"""批量读 33 省村界 shp，统一编码与字段名，写 GeoPackage (UTF-8)。

GBK 省 (河北/河南/陕西) 用 encoding='GBK'。其他省 cpg 声明 UTF-8。
字段名标准化 (按 thedavidweng/china-village-boundaries SCHEMA_MAPPING.md):
  12 位 code -> village_code,  村名 -> village_name, 省/市/县/乡镇 -> province/city/county/township name+code

用法:
    python scripts/rebuild_village_boundaries.py
    # 产出: village-boundaries/cn_villages.gpkg, cn_villages.csv
"""
import os, sys, zipfile
from pathlib import Path

import fiona
import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent / "village-boundaries"
WORK = Path(os.environ.get("TEMP", "/tmp")) / "vb_unpack"
OUT_GPKG = ROOT / "cn_villages.gpkg"
OUT_CSV = ROOT / "cn_villages.csv"

GBK_PROVINCES = {"hebei", "henan", "shaanxi"}

CODE_HINTS = ("XZQDM", "XZDM", "AREA_CODE", "PAC", "code", "DJZQDM", "村级码", "村级代码",
              "VILLAGE_CODE", "QSDM", "xzqdm", "QSDM", "cuncode")
NAME_HINTS = ("XZQMC", "NAME", "name", "村名称", "村级名", "DJZQMC", "QMC", "xzqmc",
              "VILLAGE_NAME", "MC", "cunname")
PROV_CODE = ("省级码", "省代码", "province_code", "SXBM", "省级代码", "省码")
PROV_NAME = ("省级", "省级名", "province_name", "省份", "省份名")
CITY_CODE = ("市级码", "市代码", "city_code", "城市码")
CITY_NAME = ("市级", "市级名", "city_name", "市名称", "城市")
COUNTY_CODE = ("区县级码", "区县码", "county_code", "区县代码")
COUNTY_NAME = ("区县级", "区县名", "county_name", "区县名称")
TOWN_CODE = ("乡镇级码", "乡镇码", "township_code", "乡镇代码", "乡代码")
TOWN_NAME = ("乡镇级", "乡镇名", "township_name", "乡名称", "乡镇名称")


def pick(headers, hints):
    norm = {h.replace(" ", "").lower(): h for h in headers}
    for h in hints:
        n = h.replace(" ", "").lower()
        if n in norm:
            return norm[n]
    for hint in hints:
        for h in headers:
            if hint.lower() in h.lower():
                return h
    return None


def extract_shp(zip_path, dst):
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dst)
    shps = list(dst.rglob("*.shp"))
    return shps[0] if shps else None


def fix_gbk_col_names(shp_path):
    """GBK 省 DBF 字段名也是 GBK 编码，反查 dbf 还原。"""
    try:
        import dbfread
        tbl = dbfread.DBF(str(shp_path.with_suffix(".dbf")), encoding="GBK")
        return tbl.field_names
    except Exception as e:
        return None


def main():
    OUT_GPKG.unlink(missing_ok=True)
    parts = []
    for z in sorted(ROOT.glob("village-boundaries-*.zip")):
        prov_key = z.stem.replace("village-boundaries-", "")
        is_gbk = prov_key.lower() in GBK_PROVINCES
        try:
            tmp = WORK / prov_key
            if tmp.exists():
                import shutil; shutil.rmtree(tmp)
            shp = extract_shp(z, tmp)
            if shp is None:
                print(f"SKIP {prov_key}: no .shp"); continue

            enc = "GBK" if is_gbk else "UTF-8"
            gdf = gpd.read_file(str(shp), encoding=enc)

            # GBK 省：列名乱码时，从 dbf 还原
            if is_gbk:
                good = fix_gbk_col_names(shp)
                if good and len(good) == len(gdf.columns):
                    gdf.columns = good

            cols = list(gdf.columns)
            m = {
                "village_code":  pick(cols, CODE_HINTS),
                "village_name":  pick(cols, NAME_HINTS),
                "province_code": pick(cols, PROV_CODE),
                "province_name": pick(cols, PROV_NAME),
                "city_code":     pick(cols, CITY_CODE),
                "city_name":     pick(cols, CITY_NAME),
                "county_code":   pick(cols, COUNTY_CODE),
                "county_name":   pick(cols, COUNTY_NAME),
                "township_code": pick(cols, TOWN_CODE),
                "township_name": pick(cols, TOWN_NAME),
            }
            keep = {v: k for k, v in m.items() if v}
            gdf = gdf[list(keep.keys())].rename(columns=keep)
            gdf["src_province"] = prov_key
            print(f"{prov_key:15s} rows={len(gdf):>7d}  cols={list(gdf.columns)}")
            parts.append(gdf)
        except Exception as e:
            print(f"FAIL {prov_key}: {e}", file=sys.stderr)

    if not parts:
        sys.exit("nothing to write")

    all_gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    all_gdf.to_file(str(OUT_GPKG), driver="GPKG", layer="villages")
    all_gdf.drop(columns="geometry").to_csv(str(OUT_CSV), index=False, encoding="utf-8")
    print(f"\nWROTE {len(all_gdf):,} rows -> {OUT_GPKG.name}, {OUT_CSV.name}")


if __name__ == "__main__":
    main()