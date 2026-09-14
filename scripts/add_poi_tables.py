# -*- coding: utf-8 -*-
"""在新 db 上单独补 poi_master + poi_bbox_index + poi_name.
源: 原 geocoder.db (15GB, 含 poi_master 4.7M, OSM poi 已删)
策略: ATTACH + CREATE TABLE AS SELECT, 不重建索引.
"""
import sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "geocoder.db"
DST = ROOT / "data" / "geocoder_new.db"
TABLES = ["poi_master", "poi_bbox_index", "poi_name"]


def main():
    t0 = time.time()
    src = sqlite3.connect(str(SRC), timeout=600)
    dst = sqlite3.connect(str(DST), timeout=600)
    dst.execute("PRAGMA journal_mode=DELETE")
    dst.execute("PRAGMA synchronous=NORMAL")
    dst.execute("PRAGMA temp_store=MEMORY")
    dst.execute("PRAGMA cache_size=-2000000")
    dst.execute("ATTACH DATABASE ? AS srcdb", (str(SRC),))

    cur = src.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND name IN (?,?,?) AND sql IS NOT NULL",
        TABLES,
    )
    table_sql = {row[0]: row[1] for row in cur}

    for t in TABLES:
        sql = table_sql.get(t)
        if sql is None:
            print(f"[skip] {t} no schema")
            continue
        n = src.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        t_start = time.time()
        print(f"[create] {t:<20} ({n:>10,} rows) ...", end="", flush=True)
        dst.execute(sql)
        dst.execute(f'INSERT INTO "{t}" SELECT * FROM srcdb."{t}"')
        dst.commit()
        print(f" {time.time()-t_start:.0f}s", flush=True)

    dst.execute("DETACH DATABASE srcdb")
    print(f"\n[done] {time.time()-t0:.0f}s")
    src.close()
    dst.close()


if __name__ == "__main__":
    main()
