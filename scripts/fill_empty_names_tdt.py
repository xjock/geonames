# -*- coding: utf-8 -*-
"""cn_villages_named.gpkg 全空行 (official_name 和 shp_name 都空) 用 TDT 反查补名."""
import os, sys, json, time, socket
import urllib.request, urllib.parse

os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr
from pathlib import Path

socket.setdefaulttimeout(15)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TDT_KEY = "fbaf76f74a84bc0daa3334dae5d36412"
GPKG = Path("D:/Dev/situation/geonames/village-boundaries/cn_villages_named.gpkg")

def regeo(lon, lat):
    post = json.dumps({"lon": lon, "lat": lat, "ver": 1}, separators=(",", ":"))
    url = (f"https://api.tianditu.gov.cn/geocoder?postStr={urllib.parse.quote(post)}"
           f"&type=geocode&tk={TDT_KEY}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://lbs.tianditu.gov.cn/"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())

ds = ogr.Open(str(GPKG), update=1)
lyr = ds.GetLayer(0)
lyr.SetAttributeFilter(
    "(official_name IS NULL OR trim(official_name)='') "
    "AND (shp_name IS NULL OR trim(shp_name)='')")
targets = []
for f in lyr:
    g = f.GetGeometryRef()
    if g is None or g.IsEmpty():
        continue
    c = g.Centroid()
    targets.append((f.GetFID(), c.GetX(), c.GetY()))
print(f"targets={len(targets)}", flush=True)

n_ok = 0
lyr.StartTransaction()
for fid, lon, lat in targets:
    name = None
    for attempt in range(3):
        try:
            d = regeo(lon, lat)
            ac = d.get("result", {}).get("addressComponent", {})
            name = (ac.get("village") or ac.get("poi") or ac.get("town") or "").strip()
            break
        except Exception as ex:
            if attempt == 2:
                print(f"  ERR fid={fid}: {ex}", flush=True)
            time.sleep(1.0)
    if name:
        f = lyr.GetFeature(fid)
        f.SetField("official_name", name)
        lyr.SetFeature(f)
        n_ok += 1
        print(f"  fid={fid} -> {name}", flush=True)
    time.sleep(0.35)
lyr.CommitTransaction()
print(f"updated {n_ok}/{len(targets)}", flush=True)
ds = None
print("DONE", flush=True)