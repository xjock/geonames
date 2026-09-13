# -*- coding: utf-8 -*-
"""把 tdt_regeo_hits_v2.csv 里的 275 条 TDT 反查村名 UPDATE 进 gpkg.

目标表 (3 个 gpkg 各跑一次):
- cn_villages_named.gpkg (主, 676k 行)
- cn_villages.gpkg (拆分后村级, 616k 行)
- cn_townships.gpkg (拆分后乡镇级, 60k 行)

UPDATE 条件: shp_name 为空 AND fid 匹配.
"""
import sys, csv, sqlite3
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
VB = ROOT / "village-boundaries"
HITS = VB / "tdt_regeo_hits_v2.csv"
TARGETS = [
    VB / "cn_villages_named.gpkg",
    VB / "cn_villages.gpkg",
    VB / "cn_townships.gpkg",
]


def main():
    with open(HITS, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"hits: {len(rows)}", flush=True)

    for gpkg in TARGETS:
        if not gpkg.exists():
            print(f"  skip missing: {gpkg.name}", flush=True)
            continue
        c = sqlite3.connect(str(gpkg))
        # drop 所有 rtree 触发器 (因没 spatialite, ST_IsEmpty 不能 fire)
        for (t,) in c.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'rtree_villages_geom%'"
        ).fetchall():
            c.execute(f'DROP TRIGGER IF EXISTS "{t}"')
        c.commit()
        n_upd = 0
        for r in rows:
            fid = int(r["fid"])
            name = r["tdt_name"]
            cur = c.execute(
                "UPDATE villages SET shp_name=? "
                "WHERE fid=? AND (shp_name IS NULL OR TRIM(shp_name)='')",
                (name, fid))
            n_upd += cur.rowcount
        c.commit()
        empty_after = c.execute(
            "SELECT COUNT(*) FROM villages "
            "WHERE shp_name IS NULL OR TRIM(shp_name)=''"
        ).fetchone()[0]
        size_mb = gpkg.stat().st_size / 1024 / 1024
        print(f"  {gpkg.name}: updated={n_upd} empty_after={empty_after} "
              f"size={size_mb:.0f}MB", flush=True)
        c.close()


if __name__ == "__main__":
    main()
