# -*- coding: utf-8 -*-
"""zhconv 转繁体→简体, 原地更新 poi_master.name_zh
仅对含真繁体字的行做转换 (避开已简体行无变更)
"""
import sqlite3, sys, time
from pathlib import Path
import zhconv

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"

# 简体不会用 / 繁体专用字 (高频)
TRUE_TRAD = set("臺灣繁體龍鳳龜麵飯館衛蘭醫學髮絲銀錢鐘齒當記謝陳張劉楊門開關見覺頭麥豬鳥蟲魚馬車飛機")


def main():
    db = sqlite3.connect(str(DB), timeout=300)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")

    cur = db.execute(
        "SELECT id, name_zh FROM poi_master WHERE name_zh IS NOT NULL AND name_zh != ''"
    )
    rows = cur.fetchall()
    print(f"[scan] rows={len(rows)}", flush=True)

    t0 = time.time()
    batch = []
    n_done = 0
    n_skip = 0
    n_changed = 0
    BATCH = 2000

    for pid, nz in rows:
        if not any(ch in TRUE_TRAD for ch in nz):
            n_skip += 1
            continue
        simp = zhconv.convert(nz, "zh-cn")
        if simp == nz:
            n_skip += 1
            continue
        batch.append((simp, pid))
        n_changed += 1
        if len(batch) >= BATCH:
            db.executemany("UPDATE poi_master SET name_zh = ? WHERE id = ?", batch)
            db.commit()
            batch.clear()
            n_done += BATCH
            print(f"[upd] {n_done:,}/{n_changed:,}  elapsed={time.time()-t0:.1f}s", flush=True)

    if batch:
        db.executemany("UPDATE poi_master SET name_zh = ? WHERE id = ?", batch)
        db.commit()

    print(f"[done] changed={n_changed:,}  skipped={n_skip:,}  elapsed={time.time()-t0:.1f}s")
    db.close()


if __name__ == "__main__":
    main()
