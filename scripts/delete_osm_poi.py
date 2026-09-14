# -*- coding: utf-8 -*-
"""删 poi_master 中 OSM 灌入的非行政 POI (amenity/shop/tourism/...).
条件: source='osm' AND placetype='poi'
影响: ~295 万行, db 从 15GB 缩到 ~8GB
策略: 分批 DELETE (5000/批) + incremental_vacuum (页级释放, 不重建 db)
"""
import sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"
BATCH = 5000


def main():
    db = sqlite3.connect(str(DB), timeout=600)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA busy_timeout=60000")

    n = db.execute(
        "SELECT count(*) FROM poi_master WHERE source='osm' AND placetype='poi'"
    ).fetchone()[0]
    print(f"[scan] 待删: {n:,} 行", flush=True)
    if n == 0:
        print("[done] nothing to delete")
        db.close()
        return

    t0 = time.time()
    deleted = 0
    while True:
        cur = db.execute(
            "DELETE FROM poi_master WHERE id IN "
            "(SELECT id FROM poi_master WHERE source='osm' AND placetype='poi' LIMIT ?)",
            (BATCH,),
        )
        if cur.rowcount == 0:
            break
        deleted += cur.rowcount
        db.commit()
        if deleted % 50000 == 0:
            db.execute("PRAGMA incremental_vacuum(1000)")
            print(f"  {deleted:,}/{n:,}  elapsed={time.time()-t0:.0f}s", flush=True)

    print(f"[delete] poi_master deleted = {deleted:,}", flush=True)

    cur = db.execute(
        "DELETE FROM poi_bbox_index WHERE poi_id NOT IN (SELECT id FROM poi_master)"
    )
    print(f"[delete] poi_bbox_index orphaned = {cur.rowcount:,}", flush=True)
    db.commit()

    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print("[ckpt] wal truncated", flush=True)

    db.execute("PRAGMA incremental_vacuum")
    print("[vacuum] incremental done", flush=True)

    print(f"", flush=True)
    print(f"=== 收尾 ===", flush=True)
    print(f"poi_master total: {db.execute('SELECT count(*) FROM poi_master').fetchone()[0]:,}", flush=True)
    for r in db.execute("SELECT source, count(*) FROM poi_master GROUP BY source ORDER BY 2 DESC"):
        print(f"  {r[0]:<10} {r[1]:>10,}", flush=True)
    print(f"[done] elapsed = {time.time()-t0:.1f}s", flush=True)
    db.close()


if __name__ == "__main__":
    main()
