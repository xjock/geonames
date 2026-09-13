# -*- coding: utf-8 -*-
"""debug 安徽 with simplify like run_one_prov."""
import os, sys, time, json
from pathlib import Path
from shapely import wkb, ops
from shapely.geometry import shape

os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr

VB = Path(__file__).resolve().parent.parent / "village-boundaries"
SRC_DATAV_JSON = VB / "_datav_china.json"
SRC_V = VB / "cn_villages.gpkg"
SRC_T = VB / "cn_townships.gpkg"
PROV_ADCODE = 340000

def ogr_to_shapely(g, do_simplify=True):
    if g is None or g.IsEmpty():
        return None
    wb = bytes(g.ExportToIsoWkb())
    try:
        s = wkb.loads(wb)
    except Exception:
        return None
    if s.is_empty:
        return None
    if not s.is_valid:
        try:
            s = s.buffer(0)
        except Exception:
            return None
        if s.is_empty:
            return None
    if do_simplify:
        try:
            if s.geom_type == 'Polygon':
                coords = s.exterior.coords if s.exterior else []
                if len(coords) > 200:
                    s = s.simplify(0.0001, preserve_topology=True)
            elif s.geom_type == 'MultiPolygon':
                for p in s.geoms:
                    if p.exterior and len(p.exterior.coords) > 200:
                        s = s.simplify(0.0001, preserve_topology=True)
                        break
        except Exception:
            pass
    return s

t0 = time.time()
with open(SRC_DATAV_JSON, encoding='utf-8') as f:
    data = json.load(f)
prov_sg = None
for feat in data['features']:
    p = feat['properties']
    try:
        ac = int(p.get('adcode', 0))
    except (TypeError, ValueError):
        continue
    if ac == PROV_ADCODE:
        prov_sg = shape(feat['geometry'])
        if not prov_sg.is_valid:
            prov_sg = prov_sg.buffer(0)
        break
env = prov_sg.bounds

t1 = time.time()
geoms = []
ds_v = ogr.Open(str(SRC_V))
lyr_v = ds_v.GetLayer(0)
ds_t = ogr.Open(str(SRC_T))
lyr_t = ds_t.GetLayer(0)
n_dropped = 0
for lyr in (lyr_v, lyr_t):
    lyr.SetSpatialFilterRect(env[0], env[1], env[2], env[3])
    lyr.ResetReading()
    for f in lyr:
        g = f.GetGeometryRef()
        sg = ogr_to_shapely(g, do_simplify=True)
        if sg is None:
            n_dropped += 1
            continue
        geoms.append(sg)
print(f"READ n={len(geoms)} dropped={n_dropped} el={time.time()-t1:.1f}s", flush=True)

t2 = time.time()
holes = prov_sg
CHUNK = 2000
for ci in range(0, len(geoms), CHUNK):
    chunk = ops.unary_union(geoms[ci:ci+CHUNK])
    geoms[ci:ci+CHUNK] = []
    if chunk.is_empty:
        continue
    holes = holes.difference(chunk)
print(f"UNION+DIFF el={time.time()-t2:.1f}s holes_area={holes.area:.6f} type={holes.geom_type}", flush=True)

polys = []
if holes.geom_type == 'Polygon':
    polys = [holes]
elif holes.geom_type == 'MultiPolygon':
    polys = list(holes.geoms)
elif holes.geom_type == 'GeometryCollection':
    for g in holes.geoms:
        if g.geom_type == 'Polygon':
            polys.append(g)
        elif g.geom_type == 'MultiPolygon':
            polys.extend(g.geoms)
polys = [p for p in polys if p.area >= 0.0001 and p.is_valid]
print(f"n_polys(>=0.0001)={len(polys)} total_area={sum(p.area for p in polys):.6f}", flush=True)
print(f"grand total={time.time()-t0:.1f}s", flush=True)