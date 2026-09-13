# -*- coding: utf-8 -*-
"""holes 反查天地图: 每省 _holes_XX.gpkg 的每个洞采样点 -> TDT reverse geocode
-> 看洞里有没有村/社区. 输出 village-boundaries/_holes_tdt.csv (增量).

用法: python tdt_holes_probe.py [省码2位, 可多个]   # 无参=全部
"""
import os, sys, json, time, csv, re, socket
import urllib.request, urllib.parse
from pathlib import Path

socket.setdefaulttimeout(15)

os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr

TDT_KEY = "fbaf76f74a84bc0daa3334dae5d36412"
VB = Path("D:/Dev/situation/geonames/village-boundaries")
OUT_CSV = VB / "_holes_tdt.csv"
MIN_AREA = 0.0001      # deg2, 与 holes 生成一致
SLEEP = 0.35
TIMEOUT = 12
RETRY = 2

def sample_points(poly):
    """按面积决定采样点数: 小洞 1, 中洞 3x3 cap9, 大洞 5x5 cap16."""
    a = poly.Area()
    n_side = 1 if a < 0.005 else (3 if a < 0.05 else 5)
    minx, miny, maxx, maxy = poly.GetEnvelope()
    pts = []
    if n_side == 1:
        c = poly.Centroid()
        if poly.Contains(c):
            pts.append((c.GetX(), c.GetY()))
        else:
            c = poly.PointOnSurface() if hasattr(poly, 'PointOnSurface') else c
            pts.append((c.GetX(), c.GetY()))
        return pts
    for i in range(n_side):
        for j in range(n_side):
            x = minx + (maxx - minx) * (i + 0.5) / n_side
            y = miny + (maxy - miny) * (j + 0.5) / n_side
            p = ogr.Geometry(ogr.wkbPoint)
            p.AddPoint_2D(x, y)
            if poly.Contains(p):
                pts.append((x, y))
    if not pts:
        c = poly.Centroid()
        pts.append((c.GetX(), c.GetY()))
    return pts[:16]

def regeo(lon, lat):
    post = json.dumps({"lon": lon, "lat": lat, "ver": 1}, separators=(",", ":"))
    url = (f"https://api.tianditu.gov.cn/geocoder?postStr={urllib.parse.quote(post)}"
           f"&type=geocode&tk={TDT_KEY}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://lbs.tianditu.gov.cn/"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())

def load_done():
    """已完成的 (adcode, fid) 集合, 支持断点续跑."""
    done = set()
    if OUT_CSV.exists():
        with open(OUT_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add((row["adcode"], row["hole_fid"]))
    return done

def main():
    codes = sys.argv[1:]
    files = []
    for f in sorted(VB.glob("_holes_*.gpkg")):
        m = re.match(r"_holes_(\d+)_([^.]+)\.gpkg", f.name)
        if not m:
            continue
        if codes and m.group(1) not in codes:
            continue
        files.append((m.group(1), m.group(2), f))
    print(f"queue {len(files)} provinces", flush=True)

    done = load_done()
    new_file = not OUT_CSV.exists()
    out_f = open(OUT_CSV, "a", encoding="utf-8", newline="")
    w = csv.writer(out_f)
    if new_file:
        w.writerow(["adcode", "prov_name", "hole_fid", "area_deg2",
                    "n_pts", "n_hit", "villages", "towns"])

    for code, name, f in files:
        ds = ogr.Open(str(f))
        lyr = ds.GetLayer(0)
        n_feat = lyr.GetFeatureCount()
        t0 = time.time()
        n_hole_done = 0
        for feat in lyr:
            key = (str(int(code) * 10000), str(feat.GetFID()))
            if key in done:
                continue
            area = feat.GetField("area_deg2") or 0.0
            if area < MIN_AREA:
                continue
            g = feat.GetGeometryRef()
            if g is None or g.IsEmpty():
                continue
            pts = sample_points(g)
            villages, towns = set(), set()
            n_hit = 0
            for lon, lat in pts:
                for attempt in range(RETRY + 1):
                    try:
                        d = regeo(lon, lat)
                        ac = d.get("result", {}).get("addressComponent", {})
                        v = (ac.get("village") or ac.get("poi") or "").strip()
                        t = (ac.get("town") or "").strip()
                        if v:
                            villages.add(v)
                            n_hit += 1
                        elif t:
                            towns.add(t)
                        break
                    except Exception as ex:
                        if attempt == RETRY:
                            print(f"  ERR {code} fid={feat.GetFID()} "
                                  f"({lon:.4f},{lat:.4f}): {ex}", flush=True)
                        time.sleep(1.0)
                time.sleep(SLEEP)
            w.writerow([int(code) * 10000, name, feat.GetFID(),
                        f"{area:.6f}", len(pts), n_hit,
                        "|".join(sorted(villages)), "|".join(sorted(towns))])
            out_f.flush()
            n_hole_done += 1
        ds = None
        print(f"[{code} {name}] holes={n_feat} probed={n_hole_done} "
              f"el={time.time()-t0:.0f}s", flush=True)
    out_f.close()
    print("DONE", flush=True)

if __name__ == "__main__":
    main()