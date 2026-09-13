# -*- coding: utf-8 -*-
"""天地图 v2/search 离线补名: 遍历 gpkg miss 行, 用 shp_name 查 center+adminCode。

流程:
1. 读 gpkg 全部 miss 行 (官方名空) -> 用 shp_name 查 v2/search
2. 命中: 写补名到 tdt_geocode_hits.csv
3. 用户审核后并入 gpkg (手动合并)

用法:
    python scripts/tdt_geocode.py --limit 5000
    # 限 5000 行先验证命中率, 全量跑可设 --limit 0

特点:
- 每请求本地 SQLite 缓存 (tdt_cache.db), 重跑零浪费
- 失败 3 次重试, 限速 0.4s/请求 (每日配额2000-6000, 安全线内)
- UTF-8 body 文件传, 避开前面探测踩的编码坑
"""
import csv
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_IN = ROOT / "village-boundaries" / "cn_villages_named.csv"
OUT_HITS = ROOT / "village-boundaries" / "tdt_geocode_hits.csv"
CACHE = ROOT / "tdt_cache.db"
TDT_KEY = "fbaf76f74a84bc0daa3334dae5d36412"
URL = "https://api.tianditu.gov.cn/v2/search"

# village code12 前 9 位 = 天地图 9 位国标码 (156110108), code12[:9] + "156" 前缀
SPEC_PREFIX = "156"


def init_db():
    conn = sqlite3.connect(str(CACHE))
    conn.execute("CREATE TABLE IF NOT EXISTS q (key TEXT PRIMARY KEY, hit TEXT)")
    return conn


def to_specify(code12: str) -> str | None:
    """12 位统计局码 -> 天地图 9 位市级国标码 (156+code12 前 4 位+00)
    县级 adminCode 不在 v2/search 白名单, 用市级限定 + 关键字后缀兜底"""
    if not code12 or len(code12) < 4:
        return None
    return SPEC_PREFIX + code12[:4] + "00"


def kws(name: str):
    """关键字变体: 原名/原名+村/原名+社区/原名+居委会 顺序试"""
    yield name
    if not name.endswith(("村", "社区", "居委会")):
        for suf in ("村", "社区", "居委会"):
            yield name + suf


def search_one(q: str, specify: str | None, retry=3):
    """天地图 v2/search GET, postStr + type=query + specify 限定
    返回首条 poi dict 或 None"""
    payload = {"keyWord": q, "queryType": 12, "start": "0", "count": "1",
               "show": "2"}
    if specify:
        payload["specify"] = specify
    post_str = json.dumps(payload, ensure_ascii=False)
    url = (f"{URL}?postStr={urllib.parse.quote(post_str, safe=':,{}')}"
           f"&type=query&tk={TDT_KEY}")
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://lbs.tianditu.gov.cn/"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            if data.get("status", {}).get("infocode") == 1000:
                pois = data.get("pois") or []
                return pois[0] if pois else None
            return None
        except urllib.error.HTTPError as e:
            if e.code in (400, 403):
                return None  # spec/code 非法或限流, 跳过
            last = e
            time.sleep(1.5 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last if last else RuntimeError("empty")


def main():
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    conn = init_db()
    hits_out = open(OUT_HITS, "w", newline="", encoding="utf-8")
    wr = csv.writer(hits_out)
    wr.writerow(["code12", "hit_name", "adminCode", "lon", "lat",
                 "src_province", "shp_name", "query"])

    n_miss = n_query = n_hit = 0
    t0 = time.time()
    with open(CSV_IN, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for p in r:
            if p.get("official_name"):
                continue
            n_miss += 1
            shp = p.get("shp_name")
            code12 = p.get("code12", "")
            prov = p.get("src_province", "")
            if not shp or shp == "nan":
                continue
            cache_key = f"{prov}|{shp}"
            row = conn.execute(
                "SELECT hit FROM q WHERE key=?", (cache_key,)).fetchone()
            if row is not None:
                hits = json.loads(row[0]) if row[0] else None
            else:
                spec = to_specify(code12)
                hits = None
                tried = []
                for kw in kws(shp):
                    try:
                        r = search_one(kw, spec)
                        n_query += 1
                        tried.append(kw)
                        if r:
                            hits = r
                            break
                        time.sleep(0.2)
                    except Exception as e:
                        print(f"[{n_miss}] ERR {kw}: {e}")
                        break
                time.sleep(0.2)
                conn.execute("INSERT OR REPLACE INTO q(key, hit) VALUES(?,?)",
                             (cache_key, json.dumps(hits, ensure_ascii=False)))
                conn.commit()
            if hits:
                n_hit += 1
                lonlat = hits.get("lonlat", ",").split(",")
                wr.writerow([code12, hits.get("name", ""),
                             hits.get("countyCode", "") or hits.get("adminCode", ""),
                             lonlat[0] if len(lonlat) > 1 else "",
                             lonlat[1] if len(lonlat) > 1 else "",
                             prov, shp, shp])
                hits_out.flush()
            if n_miss % 200 == 0:
                rate = n_hit / max(n_query, 1)
                el = time.time() - t0
                print(f"[{n_miss}] queries={n_query} hits={n_hit} "
                      f"hit_rate={rate:.1%} elapsed={el:.0f}s")
            if limit and n_query >= limit:
                print(f"--limit reached ({limit})")
                break
    hits_out.close()
    rate = n_hit / max(n_query, 1)
    print(f"\nDONE miss={n_miss} queries={n_query} hits={n_hit} "
          f"hit_rate={rate:.1%} -> {OUT_HITS.name}")


if __name__ == "__main__":
    main()