# -*- coding: utf-8 -*-
"""空名行 → 天地图 v2/search 反查最近 village POI → 提取村名

策略:
- queryType=2 (POI 搜索) + specify=province + bbox=0.015° ~1.5km
- keyWord 试 "村" → "社区"
- POI name 清洗: 去 村民委员会/居委会等后缀
- 排除明显非村级 POI: 加油站, 学校, 医院, ...
- 命中 (<5km) 写 hits.csv
"""
import os, sys, json, time, re, urllib.request, urllib.parse, csv, math, sqlite3
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
VB = ROOT / "village-boundaries"
GPKG = VB / "cn_villages_named.gpkg"
OUT_CSV = VB / "tdt_regeo_hits.csv"
CACHE_DB = ROOT / "tdt_regeo_cache.db"
TDT_KEY = "fbaf76f74a84bc0daa3334dae5d36412"

PROV_SPEC = {
    "hebei": "156130000", "anhui": "156340000", "zhejiang": "156330000",
    "heilongjiang": "156230000", "shanghai": "156310000", "hongkong": "156810000",
}

NON_VILLAGE = ("加油站", "学校", "医院", "银行", "信用合作", "救援", "养老",
               "物流", "快递", "超市", "饭馆", "酒店", "宾馆", "修理",
               "卫生所", "诊所", "药店", "幼儿园", "小学", "中学", "大学",
               "供电", "水务", "热力", "天然气", "煤站", "加气", "气象",
               "地震", "派出所", "法庭", "司法", "工商所", "购物中心",
               "商场", "委员会应急避难场所", "党支部", "党群服务中心",
               "公厕", "厕所", "敬老院", "福利院", "希望小学", "汽车",
               "救援", "加气站", "变电", "热源", "水厂", "污水")


def init_cache():
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute("CREATE TABLE IF NOT EXISTS q (key TEXT PRIMARY KEY, hit TEXT)")
    return conn


def haversine(lon1, lat1, lon2, lat2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def search(spec, kw, bbox, count=30):
    post = json.dumps({"keyWord": kw, "level": 12, "mapBound": bbox,
                       "queryType": 2, "start": 0, "count": count, "specify": spec})
    url = f"https://api.tianditu.gov.cn/v2/search?postStr={urllib.parse.quote(post)}&type=query&tk={TDT_KEY}"
    req = urllib.request.Request(url, headers={"User-Agent": "tdt_regeo/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def clean_village_name(poi_name):
    n = poi_name.strip()
    n = re.sub(r"(村|社区|居委会)民委员会$", "", n)
    n = re.sub(r"(村|社区|居委会)委员会$", "", n)
    n = re.sub(r"(村|社区)委会$", "", n)
    n = re.sub(r"村民代表会议$", "", n)
    return n.strip()


def is_village_poi(poi_name):
    for nv in NON_VILLAGE:
        if nv in poi_name:
            return False
    return True


def lookup_one(spec, lon, lat, conn):
    cache_key = f"{spec}|{lon:.4f}|{lat:.4f}"
    row = conn.execute("SELECT hit FROM q WHERE key=?", (cache_key,)).fetchone()
    if row is not None:
        return json.loads(row[0]) if row[0] else None

    bbox = f"{lon-0.015},{lat-0.015},{lon+0.015},{lat+0.015}"
    best = None
    for kw in ("村", "社区"):
        if best:
            break
        try:
            d = search(spec, kw, bbox)
        except Exception as ex:
            print(f"    search ERR: {ex}", flush=True)
            time.sleep(1)
            continue
        pois = d.get("pois", [])
        for p in pois:
            if not is_village_poi(p.get("name", "")):
                continue
            ll = p.get("lonlat", "")
            if not ll or "," not in ll:
                continue
            try:
                plon, plat = [float(x) for x in ll.split(",")[:2]]
            except Exception:
                continue
            dd = haversine(lon, lat, plon, plat)
            if dd > 5000:
                continue
            cand = {
                "name": clean_village_name(p.get("name", "")),
                "poi_name": p.get("name", ""),
                "address": p.get("address", ""),
                "dist_m": int(dd),
                "kw": kw,
            }
            if best is None or dd < best["dist_m"]:
                best = cand
        time.sleep(0.3)
    conn.execute("INSERT OR REPLACE INTO q(key, hit) VALUES(?,?)",
                 (cache_key, json.dumps(best, ensure_ascii=False)))
    conn.commit()
    return best


def get_empty_rows():
    """读预生成的 _empty_pts.json (sqlite + rtree midpoint 近似 centroid)"""
    print("[1] 读空名行 ...", flush=True)
    pts_path = ROOT / "_empty_pts.json"
    if not pts_path.exists():
        sys.exit(f"missing {pts_path}; run extract first")
    with open(pts_path, encoding="utf-8") as f:
        rows = json.load(f)
    print(f"  rows: {len(rows)}", flush=True)
    for r in rows:
        r["lon"] = float(r["lon"])
        r["lat"] = float(r["lat"])
        r["fid"] = int(r["fid"])
    return rows


def main():
    conn = init_cache()
    rows = get_empty_rows()
    out_f = open(OUT_CSV, "w", newline="", encoding="utf-8")
    wr = csv.writer(out_f)
    wr.writerow(["fid", "code12", "src_province", "src_layer",
                 "lon", "lat", "tdt_name", "tdt_poi", "tdt_addr", "dist_m", "kw"])

    n_total = n_hit = n_miss = 0
    t0 = time.time()
    for i, r in enumerate(rows):
        n_total += 1
        spec = PROV_SPEC.get(r["src_province"])
        if not spec:
            continue
        try:
            hit = lookup_one(spec, r["lon"], r["lat"], conn)
        except Exception as ex:
            print(f"[{i:3d}] FATAL {r['src_province']:14s} {r['lon']:.4f},{r['lat']:.4f} "
                  f"ERR: {ex}", flush=True)
            import traceback; traceback.print_exc()
            hit = None
        if hit:
            n_hit += 1
            wr.writerow([r["fid"], r["code12"], r["src_province"], r["src_layer"],
                         f"{r['lon']:.5f}", f"{r['lat']:.5f}",
                         hit["name"], hit["poi_name"], hit["address"],
                         hit["dist_m"], hit["kw"]])
            out_f.flush()
            print(f"[{i:3d}] HIT  {r['src_province']:14s} {r['lon']:.4f},{r['lat']:.4f} "
                  f"-> {hit['dist_m']:4d}m \"{hit['name']}\"", flush=True)
        else:
            n_miss += 1
            print(f"[{i:3d}] MISS {r['src_province']:14s} {r['lon']:.4f},{r['lat']:.4f}", flush=True)
        if (i + 1) % 20 == 0:
            el = time.time() - t0
            print(f"--- progress {i+1}/{len(rows)} hit={n_hit} miss={n_miss} "
                  f"el={el:.0f}s rate={n_hit/max(n_total,1):.1%} ---", flush=True)
        time.sleep(0.3)
    out_f.close()

    el = time.time() - t0
    rate = n_hit / max(n_total, 1)
    print(f"\nDONE total={n_total} hit={n_hit} miss={n_miss} "
          f"rate={rate:.1%} elapsed={el:.0f}s -> {OUT_CSV.name}")


if __name__ == "__main__":
    main()
