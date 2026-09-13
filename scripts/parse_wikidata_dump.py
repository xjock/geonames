# -*- coding: utf-8 -*-
"""流式解析 latest-all.json.bz2: 抽 zh label + P1566 geoid, 写 SQLite.
可中断续跑: zh_label 表 UNIQUE(geoid), INSERT OR IGNORE.
进度日志每 LOG_EVERY entity.
"""
import bz2
import sqlite3
import sys
import time
from pathlib import Path

import ijson

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "wikidata_zh_cache.db"
DUMP = Path(r"F:\HIAN\wikidata\latest-all.json.bz2")
LOG_EVERY = 5000


def open_cache():
    c = sqlite3.connect(str(CACHE), timeout=300)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=300000")
    c.execute("PRAGMA wal_autocheckpoint=1000")
    # 兼容旧 schema (5 列含 label_zh_hant); 新表也用 5 列以一致
    c.execute("""
        CREATE TABLE IF NOT EXISTS zh_label (
            geoid INTEGER PRIMARY KEY,
            qid TEXT,
            label_zh TEXT,
            label_zh_hant TEXT,
            fetched_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.commit()
    return c


def load_cached_geoids(c):
    """启动时一次性把已缓存的 geoid 拉到 set, 避免每行 SELECT."""
    print("[init] load cached geoids to set ...", flush=True)
    t0 = time.time()
    s = {r[0] for r in c.execute("SELECT geoid FROM zh_label")}
    print(f"[init] cached: {len(s):,}  ({time.time()-t0:.1f}s)", flush=True)
    return s


def parse_dump():
    if not DUMP.exists():
        print(f"[err] dump 不存在: {DUMP}")
        return

    c = open_cache()
    cached = load_cached_geoids(c)
    n_entity = 0
    n_zh = 0
    n_p1566 = 0
    n_inserted = 0
    n_skip_dup = 0
    t0 = time.time()
    t_log = t0
    batch = []
    BATCH_SIZE = 2000

    f = bz2.open(DUMP, "rb")
    try:
        try:
            iter_entities = ijson.items(f, "item")
        except (OSError, ValueError) as e:
            print(f"[err] ijson 启动失败: {e}", flush=True)
            return
        for entity in iter_entities:
            n_entity += 1
            qid = entity.get("id", "")
            labels = entity.get("labels", {})
            zh = labels.get("zh")
            if not zh:
                continue
            label_zh = zh.get("value", "")
            if not label_zh:
                continue
            n_zh += 1

            claims = entity.get("claims", {})
            p1566_list = claims.get("P1566", [])
            if not p1566_list:
                continue
            n_p1566 += 1

            for claim in p1566_list:
                dv = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                # wikidata external-id 的 value 可能是 str("2802361") 或 dict({"numeric-id":..., "id":"..."})
                if isinstance(dv, dict):
                    gid = dv.get("numeric-id") or dv.get("id") or dv.get("value")
                else:
                    gid = dv  # 已是 string
                if isinstance(gid, str) and gid.startswith("Q"):
                    continue
                try:
                    geoid = int(gid)
                except (TypeError, ValueError):
                    continue
                if geoid in cached:
                    n_skip_dup += 1
                    continue
                cached.add(geoid)
                batch.append((geoid, qid, label_zh, None))
                if len(batch) >= BATCH_SIZE:
                    try:
                        c.executemany(
                            "INSERT OR IGNORE INTO zh_label(geoid, qid, label_zh, label_zh_hant) VALUES (?, ?, ?, ?)",
                            batch,
                        )
                        c.commit()
                        n_inserted += len(batch)
                    except Exception as e:
                        print(f"[ERR] batch len={len(batch)}: {e}", flush=True)
                        try:
                            c.commit()
                        except Exception:
                            pass
                        raise
                    batch = []

            if n_entity % LOG_EVERY == 0:
                t = time.time()
                rate = n_entity / (t - t0)
                print(f"[{n_entity:,}] zh={n_zh:,} p1566={n_p1566:,} ins={n_inserted:,} dup={n_skip_dup:,} batch_len={len(batch)}  rate={rate:.0f}/s  elapsed={t-t0:.0f}s", flush=True)
                if t - t_log > 30:
                    c.commit()
                    t_log = t
    except (OSError, EOFError, ValueError) as e:
        # dump 未下完 / bz2 流截断 / ijson 解析失败 → 优雅退出, 已入库数据保留
        print(f"[eof] dump 截断或损坏: {type(e).__name__}: {e}", flush=True)
        print(f"[eof] 已处理 entity={n_entity:,} inserted={n_inserted:,}", flush=True)
    finally:
        if batch:
            c.executemany(
                "INSERT OR IGNORE INTO zh_label(geoid, qid, label_zh, label_zh_hant) VALUES (?, ?, ?, ?)",
                batch,
            )
            n_inserted += len(batch)
        c.commit()
        c.close()
        f.close()
    print(f"[done] entity={n_entity:,} zh={n_zh:,} p1566={n_p1566:,} inserted={n_inserted:,}  total={time.time()-t0:.0f}s")


if __name__ == "__main__":
    parse_dump()
