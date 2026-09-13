# -*- coding: utf-8 -*-
"""覆盖式重建 cn_villages_named.gpkg:每个 zip 内**所有** shp 全收。

旧版 join_china_area_names.py 仅取每省第一个 shp,导致:
  - 上海/香港/澳门 整省缺失
  - 广东只有惠州 1514 行(全省 26,245 行丢)
  - 山东/浙江/黑龙江 多 shp 被丢弃

本版:
  - rglob 所有 shp 全部读
  - 新增 src_layer 列,记录来源 shp 文件名
  - 找不到 12 位 code 列的 shp 也保留(code12="")
  - schema 兼容旧版 + src_layer
"""
import os, sys, io, shutil, zipfile, traceback
from pathlib import Path
from collections import Counter

# Windows console defaults to cp936, breaks on any non-GBK shp basename.
# Force UTF-8 on stdout/stderr, silently substitute unencodable bytes.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
VB = ROOT / "village-boundaries"
CA = ROOT / "china_area" / "area_code_2024.csv.gz"
OUT_GPKG = VB / "cn_villages_named.gpkg"
OUT_CSV = VB / "cn_villages_named.csv"
TMP_GPKG = VB / "cn_villages_named_v6.gpkg"
TMP_CSV = VB / "cn_villages_named_v6.csv"
WORK = Path(os.environ.get("TEMP", "C:/Users/Administrator/AppData/Local/Temp")) / "vb_full_update"

CODE_COLS = ["CUN", "XZQDM", "DJZQDM", "XZQDM_1", "code", "CODE",
             "AREA_CODE", "PAC", "AAC", "xzqdm", "QSDM",
             "districtcode", "village_code", "adcode",
             "PAC_1", "AREA_CODE_1", "XZQDM_2", "TBMJ",
             "SQCDM", "SQDM", "JDXZQDM", "CJDCQDM", "ZQDM", "JDDM",
             "村代码", "乡代码", "县代码", "市代码"]
# 优先级 1: 村级名称列(更可能是村/居/社区名)
NAME_COLS_BEST = ["CJDCQMC", "CJGZQYMC", "CUNMC", "CJMC", "CJNAME",
                  "CUN_NAME", "CUN_MC", "cun_name", "cunmc",
                  "comname", "comname_1", "BLOCK_NAME", "BLOCKNAME",
                  "village_name", "村名", "村名称", "村名_1",
                  "村级名", "CUN_NAME_1", "CUN_MC_1",
                  "SQCMC", "SQMC"]
# 优先级 2: 行政区名(可能也是村级,视省而定)
NAME_COLS_OK = ["XZQMC", "DJZQMC", "xzqmc", "name", "NAME", "MC", "QMC",
                "QMC_1", "XZQMC_1", "XZQMC_2", "cname"]
# 优先级 3: 行政区级别名(应避免,但实在没有就用)
NAME_COLS_LAST = ["XZXZQMC", "XJXZQMC", "SJXZQMC", "SJGZQYMC", "DSJGZQYMC",
                  "QXJGZQYMC", "XZJGZQYMC", "sheng_name", "shi_name",
                  "xian_name", "xiang_name", "county_name", "town_name"]
# 4 级: hlj 林场/街道/管理局 (BEST/OK/LAST 都空时用)
NAME_COLS_FALLBACK = ["XZQM", "XZJM", "LYJ_NAME", "LC_NAME",
                      "乡名称", "县名称", "市名称", "SHENG_MC", "SHI_MC", "XIAN_MC", "XIANG_MC"]
# 拼接列名 — 同时支持大写与新疆小写
SEGS_ALL = [{"SHENG", "SHI", "XIAN", "XIANG", "CUN"},
            {"sheng", "shi", "xian", "xiang", "cun"}]
MOJIBAKE_CHARS = "浜鍖鎮鏂鐪甯佸囧笅閲敤嶇鎴涓紝绛囨垜鍦嚭鐜鎵鑺樋閮剼妤堟鏉鐢嫄灏濉鎬勪粠鍙鍗忔埌鍕囧撶悆浣嶇疆鍙鏋勫缓璁剧疆"


def load_codes():
    df = pd.read_csv(CA, header=None,
                     names=["code", "name", "level", "parent", "kind"],
                     dtype=str, encoding="utf-8")
    df = df[(df["code"].str.len() == 12) & (df["level"] == "5")]
    return dict(zip(df["code"], df["name"]))


def extract_all(z, dst):
    """解压 + 把每个 .shp 复制到 ASCII 名路径, 同步带所有侧文件。
    返回 [(new_shp_path, orig_stem), ...]。
    """
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(dst)
    out = []
    for idx, shp in enumerate(sorted(dst.rglob("*.shp"))):
        flat = dst / f"shp_{idx:03d}"
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
        out.append((new_shp, shp.stem))
    return out


def read_shp(p):
    """读 shp: cpg 声明优先, 否则 UTF-8 → GBK。
    用 fiona engine (pyogrio 不尊重 SHAPE_ENCODING)。
    关键: fiona SHAPE_ENCODING 可能用错编码 (Tianjin 字段名 GBK + 值 UTF-8)。
    修复: 用 dbfread 按 utf-8/gbk 独立判断每列,回填字符串值。
    """
    cpg = p.with_suffix(".cpg")
    declared = None
    if cpg.exists():
        try:
            declared = cpg.read_text(encoding="ascii", errors="ignore").strip() or None
        except Exception:
            pass

    # 1) fiona 拿 geometry + 数值 (schema 即使乱码列数对得上)
    last = None
    g = None
    for e in ([declared] if declared else []) + ["UTF-8", "GBK"]:
        if not e:
            continue
        os.environ["SHAPE_ENCODING"] = e
        try:
            g = gpd.read_file(str(p), engine="fiona")
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as ex:
            last = ex
    if g is None:
        raise RuntimeError(f"all encodings failed: {last}")

    # 2) 用 dbfread 以 latin-1 取原字节,自行 utf-8/gbk 解码对比
    try:
        import dbfread
        dbf_path = p.with_suffix(".dbf")
        try:
            tbl = dbfread.DBF(str(dbf_path), encoding="latin-1", load=False)
        except Exception:
            return g, declared or "?"
        fiona_cols = [c for c in g.columns if c != "geometry"]
        for idx, fname in enumerate(fiona_cols):
            if g[fname].dtype.kind not in ("O", "U", "S"):
                continue
            if idx >= len(tbl.fields):
                break
            dbf_fname = tbl.fields[idx].name
            # 取原 latin-1 str (即原字节 1:1)
            col_utf, col_gbk = [], []
            for rec in tbl:
                v = rec.get(dbf_fname)
                if v is None:
                    col_utf.append(None)
                    col_gbk.append(None)
                    continue
                try:
                    b = v.encode("latin-1")
                    col_utf.append(b.decode("utf-8", errors="replace"))
                    col_gbk.append(b.decode("gbk", errors="replace"))
                except Exception:
                    col_utf.append(v)
                    col_gbk.append(v)
            def score(col):
                # U+FFFD 替换符是编码失败的强信号,大幅扣分
                real, bad = 0, 0
                for v in col:
                    if v is None:
                        continue
                    for ch in v:
                        cp = ord(ch)
                        if 0x4E00 <= cp <= 0x9FFF:
                            real += 1
                        if cp == 0xFFFD or (0x80 <= cp <= 0xFF):
                            bad += 1
                return real * 10 - bad * 50
            chosen = col_utf if score(col_utf) >= score(col_gbk) else col_gbk
            g[fname] = chosen
        return g, declared or "?"
    except ImportError:
        return g, declared or "?"


def code_series(gdf, c):
    s = gdf[c]
    if s.dtype == object:
        return s.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    t = pd.to_numeric(s, errors="coerce")
    return t.map(lambda x: "" if pd.isna(x) else str(int(x)))


def find_code(gdf, codes=None):
    cols = list(gdf.columns)
    norm = {c.upper().strip(): c for c in cols}
    cand = []
    for k in CODE_COLS:
        c = norm.get(k.upper())
        if c:
            cand.append(c)
    for c in cols:
        if c in cand:
            continue
        sample = code_series(gdf, c).head(20)
        if sample.str.fullmatch(r"\d{12}").sum() >= 5:
            cand.append(c)
    best, best_score = None, 0
    for c in cand:
        s = code_series(gdf, c)
        # 优先 12 位直接命中;再试剥尾部 0 (hunan CJDCQDM 是 19 位零填充)
        score = int(s.str.fullmatch(r"\d{12}").sum())
        s_strip = s.str.rstrip("0")
        score_strip = int(s_strip.str.fullmatch(r"\d{12}").sum())
        if score_strip > score:
            score = score_strip
        # 加 china_area 命中权重 (村级码更具体, 优于县/市级 12 位)
        if score > 0 and codes:
            try:
                vals = s.dropna().astype(str)
                vals = vals[vals.str.fullmatch(r"\d{12}")].head(200).tolist()
                hit = sum(1 for v in vals if v in codes)
                score += hit * 100
            except Exception:
                pass
        if score > best_score:
            best, best_score = c, score
    return best


def find_name(gdf, exclude):
    """三档优先级找村级名: BEST > OK > LAST。
    排除掉 code 列以及非字符串列(用 dtype.kind 而非 == object 以兼容 nullable str)。
    若 BEST 命中列空率 >60% 自动回退 OK 列 (Fujian: CUNMC 19k 空,XZQMC 实为村名)。
    """
    cols = [c for c in gdf.columns
            if c != exclude and c and c.strip()
            and gdf[c].dtype.kind in ("O", "U", "S")]
    if not cols:  # 兜底:全部列
        cols = [c for c in gdf.columns if c != exclude and c and c.strip()]
    norm = {c.upper().strip(): c for c in cols}

    def _pick(priority_list):
        for cand in priority_list:
            c = norm.get(cand.upper())
            if c and c.strip() and c in gdf.columns and c != exclude:
                return c
        for cand in priority_list:
            cl = cand.lower()
            for c in cols:
                if not c or not c.strip():
                    continue
                if cl in c.lower():
                    return c
        return None

    def _nonempty_rate(c):
        if c is None or not c or not c.strip() or c not in gdf.columns:
            return 0.0
        try:
            s = gdf[c].dropna().astype(str)
            s = s[~s.str.match(r"^\s*$")]
            return len(s) / max(len(gdf), 1)
        except Exception:
            return 0.0

    best = _pick(NAME_COLS_BEST)
    if best and _nonempty_rate(best) >= 0.6:
        return best
    ok = _pick(NAME_COLS_OK)
    best_rate = _nonempty_rate(best) if best else 0.0
    if ok and _nonempty_rate(ok) > best_rate:
        return ok
    last = _pick(NAME_COLS_LAST)
    if last:
        return last
    fb = _pick(NAME_COLS_FALLBACK)
    if fb:
        return fb
    return best or ok


def normalize(gdf, codes, prov, layer, enc):
    cols = set(gdf.columns)
    code_col = find_code(gdf, codes)
    if code_col:
        s = code_series(gdf, code_col)
        # 19 位零填充 (hunan CJDCQDM):先剥尾 0 再取前 12
        long_mask = s.str.len() > 12
        if long_mask.any():
            s = s.copy()
            s.loc[long_mask] = s.loc[long_mask].str.rstrip("0").str[:12]
        gdf["code12"] = s.str.zfill(12).str[-12:]
    else:
        # 尝试拼接 (大小写都试, 新疆用小写)
        for segs in SEGS_ALL:
            if segs.issubset(cols):
                upper = all(c.isupper() for c in segs)
                key = lambda k: k.upper() if upper else k
                gdf["code12"] = (
                    code_series(gdf, key("sheng")).str.zfill(2).str[-2:]
                    + code_series(gdf, key("shi")).str.zfill(2).str[-2:]
                    + code_series(gdf, key("xian")).str.zfill(2).str[-2:]
                    + code_series(gdf, key("xiang")).str.zfill(3).str[-3:]
                    + code_series(gdf, key("cun")).str.zfill(3).str[-3:]
                )
                break
        else:
            gdf["code12"] = ""

    name_col = find_name(gdf, code_col)
    if not name_col or name_col not in gdf.columns:
        gdf["shp_name"] = ""
    else:
        gdf["shp_name"] = gdf[name_col].fillna("").astype(str)
    # per-row fallback: 主 col 空时按优先级试其他候选
    if (gdf["shp_name"].astype(str).str.strip() == "").any():
        # 按 FALLBACK > LAST > OK > BEST (非主 col) 顺序试
        tried = {name_col} if name_col else set()
        for tier in (NAME_COLS_FALLBACK, NAME_COLS_LAST, NAME_COLS_OK, NAME_COLS_BEST):
            for cand in tier:
                norm = {c.upper().strip(): c for c in gdf.columns}
                col = norm.get(cand.upper())
                if not col or col in tried or col == code_col:
                    continue
                if gdf[col].dtype.kind not in ("O", "U", "S"):
                    continue
                cand_vals = gdf[col].fillna("").astype(str).str.strip()
                empty_mask = gdf["shp_name"].astype(str).str.strip() == ""
                fillable = empty_mask & (cand_vals != "")
                if fillable.any():
                    gdf.loc[fillable, "shp_name"] = cand_vals[fillable]
                    tried.add(col)
        # final empty = ""
    gdf["official_name"] = gdf["code12"].map(codes).fillna("")
    gdf["src_province"] = prov
    gdf["src_layer"] = layer
    gdf["src_encoding"] = enc

    keep = ["code12", "official_name", "shp_name",
            "src_province", "src_layer", "src_encoding", "geometry"]
    return gdf[keep].copy(), code_col, name_col


def main():
    codes = load_codes()
    print(f"loaded {len(codes):,} village codes from china_area")

    if TMP_GPKG.exists():
        TMP_GPKG.unlink()
    parts = []
    summary = []
    miss_total = 0
    row_total = 0

    for z in sorted(VB.glob("village-boundaries-*.zip")):
        prov = z.stem.replace("village-boundaries-", "")
        tmp = WORK / prov
        shps = extract_all(z, tmp)
        for shp, orig_layer in shps:
            layer = orig_layer
            try:
                gdf, enc = read_shp(shp)
                if gdf.empty:
                    continue
                sub, code_col, name_col = normalize(gdf, codes, prov, layer, enc)
                miss = int((sub["official_name"] == "").sum())
                hit = len(sub) - miss
                miss_total += miss
                row_total += len(sub)
                parts.append(sub)
                summary.append((prov, layer, enc, len(sub),
                                code_col or "-", name_col or "-"))
                print(f"{prov:14s} {layer:35s} enc={enc:5s} "
                      f"rows={len(sub):>6d} code={code_col or '-':8s} "
                      f"name={name_col or '-'}")
            except Exception:
                print(f"FAIL {prov}/{layer}", file=sys.stderr)
                traceback.print_exc()

    if not parts:
        sys.exit("nothing to write")

    print(f"\nconcat {len(parts)} parts, {row_total:,} rows total...")
    all_gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    before = len(all_gdf)
    # 优先按 code12 全局去重 (保留首条),空 code12 用 (prov,layer,name) 兜底
    has_code = all_gdf["code12"].astype(str).str.fullmatch(r"\d{12}")
    with_code = all_gdf[has_code].drop_duplicates(subset=["code12"], keep="first")
    no_code = all_gdf[~has_code].drop_duplicates(
        subset=["src_province", "src_layer", "shp_name"], keep="first"
    )
    all_gdf = pd.concat([with_code, no_code], ignore_index=True)
    all_gdf = gpd.GeoDataFrame(all_gdf, crs="EPSG:4326")
    print(f"dedup by code12 (w/ fallback prov,layer,name): {before:,} -> {len(all_gdf):,}")

    all_gdf.to_file(str(TMP_GPKG), driver="GPKG", layer="villages")
    all_gdf.drop(columns="geometry").to_csv(str(TMP_CSV), index=False, encoding="utf-8")
    print(f"\nWROTE {len(all_gdf):,} rows -> {TMP_GPKG.name}")
    print(f"official_name hit rate {(row_total-miss_total)/max(row_total,1):.1%}")
    print(f"shp processed {len(summary)}")


if __name__ == "__main__":
    main()