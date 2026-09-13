# -*- coding: utf-8 -*-
"""Wikidata zh label JOIN 回 poi_master.
缓存表 wikidata_zh_cache.zh_label(geoid PK, qid, label_zh, label_zh_hant)
目标: UPDATE poi_master.name_zh + INSERT poi_name WHERE source='geonames' AND 缺真中文.
不覆盖已有真中文.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"
CACHE = ROOT / "data" / "wikidata_zh_cache.db"


def main():
    cache = sqlite3.connect(str(CACHE), timeout=120)
    cache.execute("PRAGMA journal_mode=WAL")

    n_wd = cache.execute("SELECT COUNT(*) FROM zh_label").fetchone()[0]
    n_wd_zh = cache.execute("SELECT COUNT(*) FROM zh_label WHERE label_zh IS NOT NULL AND label_zh != ''").fetchone()[0]
    print(f"[cache] 总行: {n_wd:,}  其中有 zh label: {n_wd_zh:,}")
    if n_wd == 0:
        print("[err] 缓存空, 先跑 parse_wikidata_dump.py")
        return

    db = sqlite3.connect(str(DB), timeout=300)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")

    print("[1/3] 候选: geonames 行 + 缺真中文 + wikidata 命中")
    db.execute("ATTACH DATABASE ? AS wd", (str(CACHE),))
    db.execute("DROP TABLE IF EXISTS tmp_wd_pm")
    db.execute("CREATE TEMP TABLE tmp_wd_pm (pm_id INT, geoid INT)")
    db.execute("""
        INSERT INTO tmp_wd_pm
        SELECT p.id, CAST(p.source_id AS INTEGER)
        FROM poi_master p
        WHERE p.source='geonames'
          AND p.source_id GLOB '[0-9]*'
          AND (p.name_zh IS NULL OR p.name_zh = '' OR p.name_zh NOT GLOB '*[一-龥]*')
          AND EXISTS (SELECT 1 FROM wd.zh_label w WHERE w.geoid = CAST(p.source_id AS INTEGER))
    """)
    db.commit()
    n_pm = db.execute("SELECT COUNT(*) FROM tmp_wd_pm").fetchone()[0]
    print(f"  候选 pm 行: {n_pm:,}")
    if n_pm == 0:
        return

    print("[2/3] JOIN 取 zh label")
    cur = db.execute("""
        SELECT t.pm_id, w.label_zh
        FROM tmp_wd_pm t
        JOIN wd.zh_label w ON w.geoid = t.geoid
        WHERE w.label_zh IS NOT NULL AND w.label_zh != ''
    """)
    cand = {}
    for pm_id, label in cur:
        if not any('一' <= c <= '鿿' for c in label):
            continue
        prev = cand.get(pm_id)
        if prev is None or len(label) < len(prev):
            cand[pm_id] = label
    print(f"  候选 (含汉字): {len(cand):,}")

    sorted_cand = sorted(cand.items(), key=lambda x: x[1])[:10]
    print("  === 前 10 条 ===")
    for pm_id, label in sorted_cand:
        r = db.execute("""
            SELECT COALESCE(name_en,''), COALESCE(name_zh,''), COALESCE(cc,'')
            FROM poi_master WHERE id=?
        """, (pm_id,)).fetchone()
        try:
            print(f"    pm={pm_id:>7} en='{r[0][:30]}' cc={r[2]} -> zh='{label}'")
        except UnicodeEncodeError:
            print(f"    pm={pm_id:>7} en={r[0][:30]!r} -> zh={label!r}")

    if "--write" not in sys.argv:
        print("\n(传 --write 才会写库)")
        return

    print("[3/3] UPDATE + INSERT poi_name")
    BATCH = 5000
    batch_upd = []
    batch_pn = []
    n_upd = 0
    n_pn = 0
    for pm_id, label in cand.items():
        batch_upd.append((label, pm_id))
        batch_pn.append((pm_id, label))
        if len(batch_upd) >= BATCH:
            cur = db.executemany("""
                UPDATE poi_master SET name_zh = ?
                WHERE id = ? AND (name_zh IS NULL OR name_zh = ''
                    OR name_zh NOT GLOB '*[一-龥]*')
            """, batch_upd)
            n_upd += cur.rowcount
            for pid, lab in batch_pn:
                cur = db.execute("""
                    INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source)
                    VALUES (?, 'zh', ?, 0, 'wikidata')
                """, (pid, lab))
                n_pn += cur.rowcount
            db.commit()
            batch_upd = []
            batch_pn = []
    if batch_upd:
        cur = db.executemany("""
            UPDATE poi_master SET name_zh = ?
            WHERE id = ? AND (name_zh IS NULL OR name_zh = ''
                OR name_zh NOT GLOB '*[一-龥]*')
        """, batch_upd)
        n_upd += cur.rowcount
        for pid, lab in batch_pn:
            cur = db.execute("""
                INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source)
                VALUES (?, 'zh', ?, 0, 'wikidata')
            """, (pid, lab))
            n_pn += cur.rowcount
        db.commit()

    print(f"  updated name_zh: {n_upd:,}")
    print(f"  inserted poi_name: {n_pn:,}")
    db.execute("DETACH DATABASE wd")


if __name__ == "__main__":
    main()
