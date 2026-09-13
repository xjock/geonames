# -*- coding: utf-8 -*-
"""v2: 把 china_area CSV join 到 village-boundaries shp。

修补 v1 的问题:
- 多省 shp 列名不规范 (SHENG/XIAN/XIANG/CUN, xzqdm, AREA_CODE 等) → 加宽候选
- 多数省实际是 GBK 编码 (不仅是 河北/河南/陕西) → 先 GBK, 失败回 UTF-8
- gpkg 写入 FieldError: 列名重复 → 合并前重命名为 province_xxx
- 部分省 12位code 需拼接 → 加拼接触发器

用法:
    python scripts/join_china_area_names.py
产出:
    village-boundaries/cn_villages_named.gpkg  (UTF-8, 含 geometry)
    village-boundaries/cn_villages_named.csv   (无几何)
"""
import os, sys, zipfile
from collections import Counter
from pathlib import Path

import fiona
import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
VB = ROOT / "village-boundaries"
CA = ROOT / "china_area" / "area_code_2024.csv.gz"
OUT_GPKG = VB / "cn_villages_named.gpkg"
OUT_CSV = VB / "cn_villages_named.csv"
WORK = Path(os.environ.get("TEMP", "/tmp")) / "vb_named_v2"

# 常见 12位码列名候选 (优先级)
CODE_COLS = ["CUN", "XZQDM", "DJZQDM", "XZQDM_1", "code", "CODE",
             "AREA_CODE", "PAC", "AAC", "xzqdm", "QSDM",
             "districtcode", "xzqdm", "village_code", "adcode"]
NAME_COLS = ["CUN_MC", "XZQMC", "DJZQMC", "name", "NAME", "MC", "QMC",
             "xzqmc", "village_name", "cname"]
# 拼接省/县/乡/村码列
PART_COLS = {"SHENG": 2, "SHI": 2, "XIAN": 6, "XIANG": 9, "CUN": 12}


def load_codes():
    df = pd.read_csv(CA, header=None,
                     names=["code", "name", "level", "parent", "kind"],
                     dtype=str, encoding="utf-8")
    df = df[df["code"].str.len() == 12]
    return dict(zip(df["code"], df["name"]))


def extract(z, dst):
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(dst)
    return next(iter(dst.rglob("*.shp")), None)


# UTF-8 被误按 GBK 解码后的高频乱码特征字（用于自动识别编码错读）
MOJIBAKE_CHARS = "浜鍖鎮鏂鐪甯佸囧笅閲敤嶇鎴涓紝绛囨垜鍦嚭鐜鎵鑺樋閮剼妤堟鏉鐢嫄灏濉鎬勪粠鍙鍗忔埌鍕囧撶悆浣嶇疆鍙鏋勫缓璁剧疆"
MOJIBAKE_SET = set(MOJIBAKE_CHARS)


def has_mojibake(gdf):
    """乱码判据: U+FFFD 任一即乱码; 特征字按字符密度 >20% 才算
    (绛/濉 等字既见于乱码也见于正常地名, 但乱码串近乎全可疑字符)"""
    for c in gdf.columns:
        if "�" in str(c):
            return True
        if gdf[c].dtype != object:
            continue
        s = gdf[c].dropna().astype(str)
        joined = "".join(s)
        if "�" in joined:
            return True
        if not joined:
            continue
        hits = sum(ch in MOJIBAKE_SET for ch in joined)
        if hits / len(joined) > 0.2:
            return True
    return False


def read_shp(shp_path):
    """读 .cpg 声明编码优先; 乱码/异常则回退 UTF-8 -> GBK, 以乱码检测定夺。"""
    cpg = shp_path.with_suffix(".cpg")
    declared = None
    if cpg.exists():
        declared = cpg.read_text(encoding="ascii", errors="ignore").strip() or None
    tries = ([declared] if declared else []) + ["UTF-8", "GBK"]
    last = None
    for e in tries:
        try:
            gdf = gpd.read_file(str(shp_path), encoding=e)
        except Exception:
            continue
        if not has_mojibake(gdf):
            return gdf, e
        last = (gdf, e)
    if last:
        return last
    raise RuntimeError("all encodings failed")


def code_series(gdf, c):
    """列转数字字符串: 数值列去浮点尾巴, 缺失留空"""
    s = gdf[c]
    if s.dtype == object:
        return s.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    t = pd.to_numeric(s, errors="coerce")
    return t.map(lambda x: "" if pd.isna(x) else str(int(x)))


def find_code(gdf):
    """候选列必须真含 12 位数字, 命中最多者胜出 (排除 OBJECTID/MSSM 等ID列)"""
    cols = list(gdf.columns)
    norm = {c.upper().strip(): c for c in cols}
    cand_cols = []
    for cand in CODE_COLS:
        c = norm.get(cand.upper())
        if c:
            cand_cols.append(c)
    for c in cols:
        if c in cand_cols:
            continue
        sample = code_series(gdf, c).head(20)
        if sample.str.fullmatch(r"\d{12}").sum() >= 5:
            cand_cols.append(c)
    best, best_score = None, 0
    for c in cand_cols:
        s = code_series(gdf, c)
        score = int(s.str.fullmatch(r"\d{12}").sum())
        if score > best_score:
            best, best_score = c, score
    return best


def find_name(gdf, exclude):
    cols = [c for c in gdf.columns if c != exclude]
    norm = {c.upper().strip(): c for c in cols}
    for cand in NAME_COLS:
        c = norm.get(cand.upper())
        if c: return c
    return None


def main():
    codes = load_codes()
    print(f"loaded {len(codes):,} village/居委会 names")

    # 1) china_area 直接当村级 POI 名录（官方 2024 中文名，无需 join shp）
    ca = pd.read_csv(CA, header=None,
                     names=["code", "name", "level", "parent", "kind"],
                     dtype=str, encoding="utf-8")
    ca = ca[(ca["code"].str.len() == 12) & (ca["level"] == "5")]
    ca = ca.rename(columns={"code": "village_code", "name": "village_name"})
    ca = ca[["village_code", "village_name", "parent", "kind"]]
    ca.to_csv(ROOT / "china_area" / "cn_village_poi_2024.csv", index=False, encoding="utf-8")
    print(f"WROTE china_area/cn_village_poi_2024.csv ({len(ca):,} rows)")

    # 2) join shp geometry (best-effort)
    OUT_GPKG.unlink(missing_ok=True)
    parts = []
    misses = Counter()

    for z in sorted(VB.glob("village-boundaries-*.zip")):
        prov = z.stem.replace("village-boundaries-", "")
        tmp = WORK / prov
        if tmp.exists():
            import shutil; shutil.rmtree(tmp)
        shp = extract(z, tmp)
        if shp is None:
            print(f"SKIP {prov}: no .shp"); continue
        try:
            gdf, enc = read_shp(shp)
            segs = {"SHENG", "SHI", "XIAN", "XIANG", "CUN"}
            code_col = find_code(gdf)
            if code_col:
                gdf["code12"] = code_series(gdf, code_col).str.zfill(12).str[-12:]
            elif segs.issubset(set(gdf.columns)):
                gdf["code12"] = (
                    code_series(gdf, "SHENG").str.zfill(2).str[-2:] +
                    code_series(gdf, "SHI").str.zfill(2).str[-2:] +
                    code_series(gdf, "XIAN").str.zfill(2).str[-2:] +
                    code_series(gdf, "XIANG").str.zfill(3).str[-3:] +
                    code_series(gdf, "CUN").str.zfill(3).str[-3:]
                )
            else:
                print(f"SKIP {prov}: no code col (cols={list(gdf.columns)})"); continue
            name_col = find_name(gdf, code_col)

            gdf["official_name"] = gdf["code12"].map(codes)
            miss = int(gdf["official_name"].isna().sum())
            hits = len(gdf) - miss
            misses[prov] += miss
            print(f"{prov:15s} enc={enc:5s} rows={hits:>6d} hit {miss:>5d} miss "
                  f"code={code_col},name={name_col}")

            keep = ["code12", "official_name", "geometry"]
            if name_col:
                keep.append(name_col)
            sub = gdf[keep].copy()
            sub["src_province"] = prov
            if name_col:
                sub = sub.rename(columns={name_col: "shp_name"})
            parts.append(sub)
        except Exception as e:
            print(f"FAIL {prov}: {e}", file=sys.stderr)

    if not parts:
        sys.exit("nothing to write")
    all_gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    all_gdf.to_file(str(OUT_GPKG), driver="GPKG", layer="villages")
    all_gdf.drop(columns="geometry").to_csv(str(OUT_CSV), index=False, encoding="utf-8")
    print(f"\nWROTE {len(all_gdf):,} rows -> {OUT_GPKG.name}")
    if misses:
        miss_df = pd.DataFrame(
            [(p, n) for p, n in misses.items() if n > 0],
            columns=["province", "miss"]
        ).sort_values("miss", ascending=False)
        print("\n未命中:")
        print(miss_df.to_string(index=False))


if __name__ == "__main__":
    main()