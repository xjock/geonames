# -*- coding: utf-8 -*-
"""干跑: 通过 Wikidata SPARQL endpoint 拉 geoid→zh-label, 缓存 SQLite.
只查当前 poi_master 中 source='geonames' 的 geoid 范围.
"""
import json
import os
import socket
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import socks  # PySocks
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", 1080)
    socket.socket = socks.socksocket
    print("[proxy] SOCKS5 127.0.0.1:1080 已启用")
except ImportError:
    print("[proxy] pysocks 未装, 直连")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"
CACHE = ROOT / "data" / "wikidata_zh_cache.db"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = "geocoder-wikidata/0.1 (contact: ops@local)"
SLEEP = 1.5


def query_sparql(sparql, retries=3):
    url = ENDPOINT + "?query=" + urllib.parse.quote(sparql) + "&format=json"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                time.sleep(15)
                continue
            if attempt == retries - 1:
                raise
            time.sleep(5)
    return None


def ensure_cache(c):
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


def main():
    src = sqlite3.connect(str(DB), timeout=120)
    geoids = [r[0] for r in src.execute(
        'SELECT DISTINCT CAST(source_id AS INTEGER) FROM poi_master '
        "WHERE source='geonames' AND source_id GLOB '[0-9]*' "
        'AND lat IS NOT NULL AND lon IS NOT NULL '
        "AND (name_zh IS NULL OR name_zh = '' OR name_zh NOT GLOB '*[一-龥]*')"
    ).fetchall()]
    src.close()
    print(f"待查 geoid: {len(geoids):,}")

    cache = sqlite3.connect(str(CACHE), timeout=60)
    ensure_cache(cache)

    if "--write" not in sys.argv:
        print("\n=== 干跑: 拉前 3 个 geoid 看是否连通 ===")
        for g in geoids[:3]:
            q = (
                "SELECT ?qid ?zh ?zhHant WHERE {\n"
                "  ?qid wdt:P1566 '" + str(g) + "' .\n"
                "  OPTIONAL { ?qid rdfs:label ?zh . FILTER(LANG(?zh)='zh') }\n"
                "  OPTIONAL { ?qid rdfs:label ?zhHant . FILTER(LANG(?zhHant)='zh-Hant') }\n"
                "} LIMIT 1"
            )
            t0 = time.time()
            r = query_sparql(q)
            dt = time.time() - t0
            if not r or not r["results"]["bindings"]:
                print(f"  geoid={g}: 无 QID  ({dt:.1f}s)")
                continue
            row = r["results"]["bindings"][0]
            zh = row.get("zh", {}).get("value", "")
            zhH = row.get("zhHant", {}).get("value", "")
            qid = row.get("qid", {}).get("value", "").rsplit("/", 1)[-1]
            print(f"  geoid={g}  QID={qid}  zh='{zh}'  zh-Hant='{zhH}'  ({dt:.1f}s)")
            time.sleep(SLEEP)
        cache.close()
        return

    # 实跑: VALUES 批量
    done = {r[0] for r in cache.execute("SELECT geoid FROM zh_label").fetchall()}
    todo = [g for g in geoids if g not in done]
    print(f"已缓存: {len(done):,}, 待拉: {len(todo):,}")
    PAGE = 100
    n_ok = n_zh = n_err = 0
    for off in range(0, len(todo), PAGE):
        chunk = todo[off:off + PAGE]
        binds = "\n".join(
            '  {{ ?qid wdt:P1566 "{0}" . BIND("{0}" AS ?geoid) }}'.format(g) for g in chunk
        )
        sparql = (
            "SELECT ?geoid ?zh ?zhHant WHERE {\n"
            "  { SELECT ?qid ?geoid WHERE {\n"
            "    %b\n"
            "  } }\n"
            "  OPTIONAL { ?qid rdfs:label ?zh . FILTER(LANG(?zh)='zh') }\n"
            "  OPTIONAL { ?qid rdfs:label ?zhHant . FILTER(LANG(?zhHant)='zh-Hant') }\n"
            "}"
        ) % binds.encode("utf-8")
        t0 = time.time()
        try:
            r = query_sparql(sparql)
        except Exception as e:
            n_err += len(chunk)
            print(f"  ERR chunk {off}: {e}")
            time.sleep(SLEEP)
            continue
        dt = time.time() - t0
        rows = r["results"]["bindings"] if r else []
        for row in rows:
            geoid = int(row["geoid"]["value"])
            zh = row.get("zh", {}).get("value", "")
            zhH = row.get("zhHant", {}).get("value", "")
            cache.execute(
                "INSERT OR REPLACE INTO zh_label(geoid, qid, label_zh, label_zh_hant) VALUES (?, '', ?, ?)",
                (geoid, zh, zhH),
            )
            n_ok += 1
            if zh:
                n_zh += 1
        cache.commit()
        print(f"  [{off+len(chunk):,}/{len(todo):,}] rows={len(rows)} ok={n_ok} zh={n_zh} err={n_err} ({dt:.1f}s)")
        time.sleep(SLEEP)
    cache.close()


if __name__ == "__main__":
    main()
