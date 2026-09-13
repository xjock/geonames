# -*- coding: utf-8 -*-
"""干跑: 抽 5 条 name_en 缺中文 POI, 喂 TDT, 比坐标, 不写库.
输出 TDT 返回 + 距离决策 (accept / reject / nohit).
"""
import json
import math
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"
TDT = "https://api.tianditu.gov.cn/v2/search"
KEY = "fbaf76f74a84bc0daa3334dae5d36412"
MAX_DIST_KM = 50  # 坐标偏差阈值


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def tdt_search(q):
    post = json.dumps({"keyWord": q, "level": 12, "mapBound": "-180,-90,180,90",
                       "queryType": 1, "start": 0, "count": 5})
    url = TDT + "?postStr=" + urllib.parse.quote(post) + "&type=query&tk=" + KEY
    req = urllib.request.Request(url, headers={"User-Agent": "geocoder/dryrun"})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}
    hits = []
    for bucket in (data.get("area"), data.get("pois"), data.get("prompt")):
        if not bucket:
            continue
        if isinstance(bucket, dict):
            bucket = [bucket]
        for it in bucket:
            ll = it.get("lonlat", "")
            parts = ll.split(",") if ll else []
            if len(parts) != 2:
                continue
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            hits.append({
                "name": it.get("name", ""),
                "lat": lat,
                "lon": lon,
                "type": it.get("type", ""),
                "address": it.get("address", "") or it.get("adminName", ""),
            })
    return {"hits": hits}


def is_zh(s):
    if not s:
        return False
    return bool(re.search(r"[一-鿿]", s))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    sample_n = int(sys.argv[2]) if len(sys.argv) > 2 else 0  # 0=顺序抽, >0=随机
    c = sqlite3.connect(str(DB), timeout=30)

    sql = '''
        SELECT id, source, source_id, COALESCE(name_en,''), COALESCE(name_zh,''),
               lat, lon, COALESCE(cc,''), COALESCE(placetype,''), COALESCE(region,'')
        FROM poi_master
        WHERE name_en IS NOT NULL AND name_en != ''
          AND lat IS NOT NULL AND lon IS NOT NULL
          AND (name_zh IS NULL OR name_zh = '' OR length(name_zh) < 1)
    '''
    if sample_n > 0:
        sql += ' ORDER BY RANDOM() LIMIT ?'
        rows = c.execute(sql, (sample_n,)).fetchall()
    else:
        sql += ' LIMIT ?'
        rows = c.execute(sql, (n,)).fetchall()

    print(f"=== 样本 {len(rows)} 条 ===\n")
    summary = {"accept": 0, "reject": 0, "nohit": 0, "err": 0}
    for i, r in enumerate(rows, 1):
        pm_id, src, sid, nen, nzh, lat, lon, cc, pt, region = r
        print(f"[{i}] id={pm_id} {src}/{sid} {region}/{cc} {pt}")
        print(f"    en='{nen}'  zh='{nzh}'  ({lat:.4f},{lon:.4f})")
        tdt = tdt_search(nen)
        if "error" in tdt:
            print(f"    TDT ERR: {tdt['error']}")
            summary["err"] += 1
            print()
            continue
        hits = tdt.get("hits", [])
        if not hits:
            print(f"    TDT nohit")
            summary["nohit"] += 1
            print()
            continue
        chosen = None
        for h in hits:
            d = haversine(lat, lon, h["lat"], h["lon"])
            mark = ""
            if is_zh(h["name"]):
                if d <= MAX_DIST_KM:
                    mark = " <- ACCEPT"
                    chosen = (h, d)
                    break
                else:
                    mark = f" (zh 但距离 {d:.1f}km > {MAX_DIST_KM}km)"
            else:
                mark = f" (非中文 '{h['name']}', d={d:.1f}km)"
            print(f"      TDT: '{h['name']}' ({h['lat']:.4f},{h['lon']:.4f}) {h['type']} {h['address']}{mark}")
        if chosen:
            h, d = chosen
            print(f"    -> ACCEPT: name_zh='{h['name']}' (距离 {d:.1f}km)")
            summary["accept"] += 1
        else:
            print(f"    -> REJECT: 无合用命中")
            summary["reject"] += 1
        print()

    print(f"=== 汇总 ===")
    print(f"  accept={summary['accept']}  reject={summary['reject']}  nohit={summary['nohit']}  err={summary['err']}")
    c.close()


if __name__ == "__main__":
    main()
