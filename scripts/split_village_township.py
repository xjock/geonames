# -*- coding: utf-8 -*-
"""把 cn_villages_named.gpkg 拆 2 个 gpkg:
- cn_villages.gpkg   真正村级
- cn_townships.gpkg  非村级 (乡镇级 + 林场 + 保护区 + 牧场 + 农场 + 县直属 + 农垦 + 草原 + 林区)

启发式 (任一命中即 township):
- src_layer 含 林场/森工/农垦/牧场/保护区/县直属/农场/林区/草原/三调/国土
- bbox 面积 > 50 km² (中纬度粗估: dx_deg * dy_deg * 12321)

OGR sqlite dialect 提供 ST_MinX/MaxX/MinY/MaxY, 直接生成两份 gpkg.
原 cn_villages_named.gpkg 不动.
"""
import sys, subprocess, sqlite3, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
VB = ROOT / "village-boundaries"
SRC = VB / "cn_villages_named.gpkg"
DST_V = VB / "cn_villages.gpkg"
DST_T = VB / "cn_townships.gpkg"
OGR = Path("D:/Dev/toolchain/libmapping-1.0.0/bin/ogr2ogr.exe")

TOWN_KEYWORDS = (
    "林场", "森工", "农垦", "牧场", "保护区", "县直属",
    "农场", "林区", "草原", "三调", "国土",
)
AREA_THRESHOLD_KM2 = 50.0


def is_town_expr():
    parts = [f"src_layer LIKE '%{kw}%'" for kw in TOWN_KEYWORDS]
    parts.append(
        f"((ST_MaxX(geom) - ST_MinX(geom)) * "
        f"(ST_MaxY(geom) - ST_MinY(geom)) * 12321.0 > {AREA_THRESHOLD_KM2})"
    )
    return " OR ".join(parts)


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    if not OGR.exists():
        sys.exit(f"missing {OGR}")

    for p in (DST_V, DST_T):
        if p.exists():
            p.unlink()

    cols = ("fid, geom, code12, official_name, shp_name, "
            "src_province, src_layer, src_encoding, "
            "ST_MinX(geom) AS min_lon, ST_MaxX(geom) AS max_lon, "
            "ST_MinY(geom) AS min_lat, ST_MaxY(geom) AS max_lat")

    town = is_town_expr()

    for dst, label, where in [
        (DST_V, "village", f"NOT ({town})"),
        (DST_T, "township", town),
    ]:
        sql = f"SELECT {cols} FROM villages WHERE {where}"
        t0 = time.time()
        r = subprocess.run([
            str(OGR), "-f", "GPKG", "-nln", "villages", "-overwrite",
            "-sql", sql, str(dst), str(SRC),
        ], capture_output=True, text=True)
        if r.returncode != 0:
            print("STDERR:", r.stderr[-2000:], flush=True)
            sys.exit(f"ogr2ogr failed for {label}")
        size_mb = dst.stat().st_size / 1024 / 1024
        # count via sqlite
        c = sqlite3.connect(str(dst))
        n = c.execute("SELECT COUNT(*) FROM villages").fetchone()[0]
        c.close()
        print(f"[{label}] {dst.name} rows={n} size={size_mb:.0f}MB "
              f"el={time.time()-t0:.1f}s", flush=True)

    print("\nDONE")


if __name__ == "__main__":
    main()
