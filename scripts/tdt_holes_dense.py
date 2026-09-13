# -*- coding: utf-8 -*-
"""加密复核: 对 area>=0.005 deg2 且无村命中的洞, 加密网格采样再查 TDT.
输出 village-boundaries/_holes_tdt_dense.csv (同 schema + dense 标记).
断点续跑.
"""
import os, sys, json, time, csv, re, socket, math
import urllib.request, urllib.parse
from pathlib import Path

os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr

socket.setdefaulttimeout(15)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TDT_KEY = "fbaf76f74a84bc0daa3334dae5d36412"
VB = Path("D:/Dev/situation/geonames/village-boundaries")
SRC_CSV = VB / "_holes_tdt.csv"
OUT_CSV = VB / "_holes_tdt_dense.csv"
MIN_AREA = 0.005
MAX_PTS = 36
SPACING = 0.02   # ~2km
SLEEP = 0.35
VRE = re.compile(r'村|社区|居委会')

def grid_points(poly):
    a = poly.Area()
    minx, miny, maxx, maxy = poly.GetEnvelope()
    side = max(2, min(6, int(math.sqrt(a) / SPACING) + 1))
    pts = []
    for i in range(side):
        for j in range(side):
            x = minx + (maxx - minx) * (i + 0.5) / side
            y = miny + (maxy - miny) * (j + 0.5) / side
            p = ogr.Geometry(ogr.wkbPoint)
            p.AddPoint_2D(x, y)
            if poly.Contains(p):
                pts.append((x, y))
    if not pts:
        c = poly.Centroid()
        pts.append((c.GetX(), c.GetY()))
    if len(pts) > MAX_PTS:
        step = len(pts) / MAX_PTS
        pts = [pts[int(i * step)] for i in range(MAX_PTS)]
    return pts

def regeo(lon, lat):
    post = json.dumps({"lon": lon, "lat": lat, "ver": 1}, separators=(",", ":"))
    url = (f"https://api.tianditu.gov.cn/geocoder?postStr={urllib.parse.quote(post)}"
           f"&type=geocode&tk={TDT_KEY}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://lbs.tianditu.gov.cn/"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())

def main():
    targets = {}
    with open(SRC_CSV, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            a = float(r['area_deg2'])
            if a >= MIN_AREA and not (r['villages'] and VRE.search(r['villages'])):
                targets.setdefault(r['adcode'], {})[int(r['hole_fid'])] = (r['prov_name'], a)
    done = set()
    if OUT_CSV.exists():
        with open(OUT_CSV, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                done.add((r['adcode'], r['hole_fid']))
    n_target = sum(len(v) for v in targets.values())
    print(f"targets={n_target} done={len(done)}", flush=True)

    new_file = not OUT_CSV.exists()
    out_f = open(OUT_CSV, "a", encoding='utf-8', newline="")
    w = csv.writer(out_f)
    if new_file:
        w.writerow(["adcode", "prov_name", "hole_fid", "area_deg2",
                    "n_pts", "n_hit", "villages", "towns"])

    n_done = 0
    for gpkg in sorted(VB.glob('_holes_*.gpkg')):
        m = re.match(r'_holes_(\d+)_([^.]+)\.gpkg', gpkg.name)
        if not m or 'villages' in gpkg.name:
            continue
        adcode = str(int(m.group(1)) * 10000)
        tset = targets.get(adcode)
        if not tset:
            continue
        src = ogr.Open(str(gpkg))
        slyr = src.GetLayer(0)
        t0 = time.time()
        n_prov = 0
        for feat in slyr:
            fid = feat.GetFID()
            if fid not in tset or (adcode, str(fid)) in done:
                continue
            g = feat.GetGeometryRef()
            if g is None or g.IsEmpty():
                continue
            pts = grid_points(g)
            villages, towns = set(), set()
            n_hit = 0
            for lon, lat in pts:
                for attempt in range(3):
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
                        if attempt == 2:
                            print(f"  ERR {adcode} fid={fid}: {ex}", flush=True)
                        time.sleep(1.0)
                time.sleep(SLEEP)
            w.writerow([adcode, tset[fid][0], fid, f"{tset[fid][1]:.6f}",
                        len(pts), n_hit,
                        "|".join(sorted(villages))[:250],
                        "|".join(sorted(towns))[:250]])
            out_f.flush()
            n_prov += 1
            n_done += 1
        src = None
        print(f"[{m.group(2)}] dense={n_prov} el={time.time()-t0:.0f}s "
              f"total={n_done}/{n_target}", flush=True)
    out_f.close()
    print("DONE", flush=True)

if __name__ == "__main__":
    main()