# -*- coding: utf-8 -*-
"""流式读 alternateNamesV2.txt, 提取所有 zh 系 altname → 批量回灌 poi_master.name_zh (source='geonames')."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"
ALT = ROOT / "data" / "alternateNamesV2.txt"

LANG_PRIORITY = {
    "zh-CN": 1, "zh-Hans": 2, "zh": 3,
    "zh-Hant": 4, "zh-TW": 5, "zh-HK": 6, "zh-MO": 7, "zh-SG": 8,
}


def has_cjk(s):
    for ch in s:
        if 0x4E00 <= ord(ch) <= 0x9FFF:
            return True
    return False


def stream_altnames_zh():
    with open(ALT, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            try:
                geoid = int(parts[1])
            except (ValueError, IndexError):
                continue
            lang = parts[2]
            if lang not in LANG_PRIORITY:
                continue
            name = parts[3].strip()
            if not name or not has_cjk(name):
                continue
            yield geoid, lang, name


def main():
    print(f"[alt] read {ALT}", flush=True)
    best = {}
    n_seen = 0
    for geoid, lang, name in stream_altnames_zh():
        n_seen += 1
        prio = LANG_PRIORITY[lang]
        cur = best.get(geoid)
        if cur is None or prio < cur[0]:
            best[geoid] = (prio, name)
        if n_seen % 100000 == 0:
            print(f"[alt] scanned {n_seen:,} zh rows, distinct geoid={len(best):,}", flush=True)
    print(f"[alt] total zh scanned: {n_seen:,}, distinct geoid: {len(best):,}", flush=True)

    db = sqlite3.connect(str(DB), timeout=300)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA cache_size=-200000")

    print("[alt] creating temp table _alt_zh ...", flush=True)
    db.execute("DROP TABLE IF EXISTS _alt_zh")
    db.execute("CREATE TEMP TABLE _alt_zh(geoid INTEGER PRIMARY KEY, name_zh TEXT)")
    batch = []
    BATCH = 10000
    for i, (geoid, (prio, name)) in enumerate(best.items(), 1):
        batch.append((geoid, name))
        if len(batch) >= BATCH:
            db.executemany("INSERT INTO _alt_zh(geoid, name_zh) VALUES (?, ?)", batch)
            batch.clear()
        if i % 100000 == 0:
            print(f"[alt] inserting {i:,}/{len(best):,}", flush=True)
    if batch:
        db.executemany("INSERT INTO _alt_zh(geoid, name_zh) VALUES (?, ?)", batch)
    db.commit()
    db.execute("CREATE INDEX _alt_zh_idx ON _alt_zh(geoid)")

    print("[alt] UPDATE pm.name_zh ...", flush=True)
    cur = db.execute("""
        UPDATE poi_master
        SET name_zh = (SELECT a.name_zh FROM _alt_zh a WHERE a.geoid = CAST(poi_master.source_id AS INTEGER))
        WHERE source = 'geonames'
          AND EXISTS (SELECT 1 FROM _alt_zh a WHERE a.geoid = CAST(poi_master.source_id AS INTEGER))
          AND (name_zh IS NULL OR name_zh = '' OR name_zh NOT GLOB '*[一-龥]*')
    """)
    print(f"[alt] updated rows: {cur.rowcount:,}", flush=True)
    db.commit()

    n_total = db.execute("SELECT COUNT(*) FROM poi_master").fetchone()[0]
    n_zh = db.execute("SELECT COUNT(*) FROM poi_master WHERE name_zh IS NOT NULL AND name_zh!='' AND name_zh GLOB '*[一-龥]*'").fetchone()[0]
    print(f"[alt] DONE pm total={n_total:,}  zh={n_zh:,}", flush=True)


if __name__ == "__main__":
    main()
