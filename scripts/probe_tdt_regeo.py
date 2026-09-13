# -*- coding: utf-8 -*-
"""probe 天地图 reverse geocoder: 取空名行几何中心 -> 反查 -> 看能不能补名
只跑 20 条样本, 确认有收获再批量
"""
import os, sys, json, time, urllib.request, urllib.parse, subprocess
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
VB = ROOT / "village-boundaries"
GPKG = VB / "cn_villages_named.gpkg"
SQLITE = Path("D:/Dev/toolchain/libmapping-1.0.0/bin/sqlite3.exe")
TDT_KEY = "fbaf76f74a84bc0daa3334dae5d36412"

# 1) 抽 20 条空名样本 (跨省, 带 centroid)
print("[1] 抽空名样本 ...", flush=True)
sql = """
SELECT code12, src_province, src_layer, shp_name,
       ST_X(ST_Centroid(geom)) AS lon,
       ST_Y(ST_Centroid(geom)) AS lat
FROM villages
WHERE trim(shp_name) = '' OR shp_name IS NULL
ORDER BY RANDOM() LIMIT 20;
"""
r = subprocess.run([str(SQLITE), "-json", str(GPKG), sql],
                   capture_output=True, text=True)
data = json.loads(r.stdout) if r.stdout.strip() else []
print(f"  样本数: {len(data)}", flush=True)
for i, row in enumerate(data):
    print(f"  [{i}] prov={row['src_province']:14s} layer={row['src_layer'][:25]:25s} "
          f"lon={float(row['lon']):.4f} lat={float(row['lat']):.4f}", flush=True)


# 2) reverse API 端点
def call_regeo_v1(lon, lat):
    post = json.dumps({"lon": lon, "lat": lat, "ver": 1})
    url = (f"https://api.tianditu.gov.cn/geocoder/v1?postStr={urllib.parse.quote(post)}"
           f"&type=geocode&tk={TDT_KEY}")
    req = urllib.request.Request(url, headers={"User-Agent": "probe/0.1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


# 3) 完整跑 20 条
print(f"\n[2] 跑 20 条 reverse (v1) ...", flush=True)
n_hit = 0
results = []
for i, row in enumerate(data):
    lon, lat = float(row["lon"]), float(row["lat"])
    try:
        d = call_regeo_v1(lon, lat)
        result = d.get("result", {})
        aoi = result.get("addressComponent", {})
        village = aoi.get("village", "") or ""
        town = aoi.get("town", "") or ""
        addr = result.get("formatted_address", "")
        addr_last = addr.split(",")[-1].strip() if addr else ""
        hit = village or (addr_last if town and town in addr_last else "")
        if hit:
            n_hit += 1
        results.append({
            "prov": row["src_province"], "village": village,
            "town": town, "addr_last": addr_last, "addr": addr[:120],
        })
        print(f"  [{i:2d}] prov={row['src_province']:14s} "
              f"village='{village[:15]:15s}' town='{town[:15]:15s}' "
              f"last='{addr_last[:30]}'", flush=True)
    except Exception as ex:
        print(f"  [{i:2d}] prov={row['src_province']:14s} ERR: {ex}", flush=True)
        results.append({"prov": row["src_province"], "err": str(ex)})
    time.sleep(0.4)

print(f"\n[3] 命中率: {n_hit}/{len(data)}", flush=True)
# 保存原始结果
out = ROOT / "tdt_regeo_probe.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"  raw -> {out.name}", flush=True)
