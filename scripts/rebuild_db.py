# -*- coding: utf-8 -*-
"""db 物理缩文件. 不走 VACUUM (Windows 卡死), 改用 ATTACH + INSERT 重建.
每个用户表 CREATE TABLE new.X AS SELECT * FROM X, 索引/triggers 重建.
目标: 15GB → ~4-5GB (freelist 228350 页清掉)
"""
import sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "geocoder.db"
DST = ROOT / "data" / "geocoder_new.db"


def main():
    if DST.exists():
        DST.unlink()

    t0 = time.time()
    src = sqlite3.connect(str(SRC), timeout=600)
    src.execute("PRAGMA busy_timeout=60000")

    rows = src.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL"
    ).fetchall()
    tables = [
        r[1] for r in rows
        if r[0] == "table" and not r[1].startswith("sqlite_")
    ]
    indexes = [
        (r[1], r[2], r[3])
        for r in rows if r[0] == "index"
    ]
    triggers = [
        (r[2], r[3])
        for r in rows if r[0] == "trigger"
    ]
    print(f"[scan] tables={len(tables)} indexes={len(indexes)} triggers={len(triggers)}", flush=True)

    dst = sqlite3.connect(str(DST), timeout=600)
    dst.execute("PRAGMA journal_mode=DELETE")  # 不用 WAL, 简单
    dst.execute("PRAGMA synchronous=NORMAL")
    dst.execute("PRAGMA temp_store=MEMORY")
    dst.execute("PRAGMA cache_size=-2000000")  # 2GB cache

    # 源库 attach 到目标库
    dst.execute("ATTACH DATABASE ? AS srcdb", (str(SRC),))

    for t in tables:
        n = src.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        t_start = time.time()
        print(f"[create] {t:<25} ({n:>10,} rows) ...", end="", flush=True)
        dst.execute(f'CREATE TABLE "{t}" AS SELECT * FROM srcdb."{t}"')
        # 重建索引
        for name, tbl, sql in indexes:
            if tbl == t:
                dst.execute(sql)
        # 重建 triggers
        for tbl, sql in triggers:
            if tbl == t:
                dst.execute(sql)
        dst.commit()
        print(f" {time.time()-t_start:.1f}s", flush=True)

    dst.execute("DETACH DATABASE srcdb")
    dst.execute("ANALYZE")
    # 末尾 VACUUM 把新 db 整理 (此时是新库, 没历史 freelist, 应能完成)
    print("[vacuum] final pass on new db ...", flush=True)
    dst.execute("VACUUM")
    dst.close()
    src.close()

    src_size = SRC.stat().st_size / 1024 / 1024
    dst_size = DST.stat().st_size / 1024 / 1024
    print(
        f"\n[done] src={src_size:.0f}MB → new={dst_size:.0f}MB  "
        f"({time.time()-t0:.0f}s)",
        flush=True,
    )


if __name__ == "__main__":
    main()
