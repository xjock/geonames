# -*- coding: utf-8 -*-
"""在 geocoder.db 加 FTS5 (trigram) 支持高效 substring 搜索.
poi_fts(name_zh, name_en) content=poi_master rowid=id.
trigram: 3 字符以上 query 工作 (中日韩 OK).
"""
import sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"


def main():
    db = sqlite3.connect(str(DB), timeout=600)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=-2000000")

    print("[create] poi_fts virtual table ...", flush=True)
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS poi_fts USING fts5(
            name_zh,
            name_en,
            content='poi_master',
            content_rowid='id',
            tokenize='trigram'
        )
    """)
    db.commit()

    n = db.execute("SELECT count(*) FROM poi_fts").fetchone()[0]
    pm_n = db.execute("SELECT count(*) FROM poi_master").fetchone()[0]
    print(f"[check] poi_fts={n:,}  poi_master={pm_n:,}", flush=True)
    if n >= pm_n:
        print("[done] already populated")
        db.close()
        return

    t0 = time.time()
    print(f"[populate] rebuild from content table ...", flush=True)
    db.execute("INSERT INTO poi_fts(poi_fts) VALUES('rebuild')")
    db.commit()
    print(f"  done in {time.time()-t0:.0f}s", flush=True)

    print("[optimize] merge segments ...", flush=True)
    db.execute("INSERT INTO poi_fts(poi_fts) VALUES('optimize')")
    db.commit()

    print("[test]", flush=True)
    for q in ["Mandalay", "Beijing", "曼德勒", "东京"]:
        ts = time.time()
        rows = db.execute(
            "SELECT rowid FROM poi_fts WHERE poi_fts MATCH ? LIMIT 3", (q,)
        ).fetchall()
        print(f"  {q:<10} {len(rows)} hits in {(time.time()-ts)*1000:.0f}ms", flush=True)

    db.close()
    print("[done]")


if __name__ == "__main__":
    main()
