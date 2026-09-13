# -*- coding: utf-8 -*-
"""单省 sub-script: 由 find_holes.py 通过 subprocess 调用, 带 timeout."""
import os, sys, time, json, gc
from pathlib import Path
from shapely import wkb, ops
from shapely.geometry import shape

os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr
from shapely.io import to_wkb

PROV_ADCODE = int(sys.argv[1])
VB = Path(__file__).resolve().parent.parent / "village-boundaries"
SRC_DATAV_JSON = VB / "_datav_china.json"
SRC_V = VB / "cn_villages.gpkg"
SRC_T = VB / "cn_townships.gpkg"
DST_DIR = VB
MIN_HOLE_AREA_DEG2 = 0.0001


def ogr_to_shapely(g):
    if g is None or g.IsEmpty():
        return None
    wb = bytes(g.ExportToIsoWkb())
    try:
        s = wkb.loads(wb)
    except Exception:
        return None
    if s.is_empty:
        return None
    # invalid: buffer(0) 修复 (但仅 invalid 时才用)
    if not s.is_valid:
        try:
            s = s.buffer(0)
        except Exception:
            return None
        if s.is_empty:
            return None
    # simplify 复杂 poly (防 OOM in union)
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


def main():
    t_total = time.time()
    with open(SRC_DATAV_JSON, encoding='utf-8') as f:
        data = json.load(f)
    prov_sg = None
    prov_name = None
    prov_code = None
    for feat in data['features']:
        p = feat['properties']
        try:
            ac = int(p.get('adcode', 0))
        except (TypeError, ValueError):
            continue
        if ac != PROV_ADCODE:
            continue
        prov_sg = shape(feat['geometry'])
        if not prov_sg.is_valid:
            prov_sg = prov_sg.buffer(0)
        prov_name = p.get('name', '')
        prov_code = ac // 10000
        break
    if prov_sg is None:
        print(f"NO_PROV {PROV_ADCODE}", flush=True)
        sys.exit(1)

    env = prov_sg.bounds
    t1 = time.time()
    geoms = []
    n_poly = 0
    ds_v = ogr.Open(str(SRC_V))
    lyr_v = ds_v.GetLayer(0)
    ds_t = ogr.Open(str(SRC_T))
    lyr_t = ds_t.GetLayer(0)
    for lyr in (lyr_v, lyr_t):
        lyr.SetSpatialFilterRect(env[0], env[1], env[2], env[3])
        lyr.ResetReading()
        for f in lyr:
            g = f.GetGeometryRef()
            sg = ogr_to_shapely(g)
            if sg is None:
                continue
            geoms.append(sg)
            n_poly += 1
    lyr_v.SetSpatialFilter(None)
    lyr_t.SetSpatialFilter(None)
    print(f"READ n={n_poly} el={time.time()-t1:.1f}s", flush=True)

    t2 = time.time()
    holes = prov_sg
    union_err = None
    diff_err = None
    if geoms:
        # chunked: 每 chunk union 后立即 diff holes (不累计 acc)
        CHUNK = 2000
        try:
            for ci in range(0, len(geoms), CHUNK):
                chunk = ops.unary_union(geoms[ci:ci+CHUNK])
                geoms[ci:ci+CHUNK] = []  # release refs
                if chunk.is_empty:
                    continue
                try:
                    holes = holes.difference(chunk)
                except Exception as e:
                    diff_err = f"diff chunk {ci//CHUNK+1}: {e}"
                    print(f"DIFF CHUNK ERR {ci//CHUNK+1}: {e}", flush=True)
                    break
                # chunk log 抑制
        except Exception as e:
            union_err = str(e)
        geoms = None
    print(f"UNION+DIFF el={time.time()-t2:.1f}s "
          f"holes_area={holes.area if holes else 0:.4f}"
          f"{f' UNION_ERR={union_err}' if union_err else ''}"
          f"{f' DIFF_ERR={diff_err}' if diff_err else ''}", flush=True)

    if holes is None or holes.is_empty:
        print(f"DONE 100%_covered total={time.time()-t_total:.1f}s",
              flush=True)
        return

    out_path = DST_DIR / f"_holes_{prov_code:02d}_{prov_name}.gpkg"
    if out_path.exists():
        out_path.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out_ds = drv.CreateDataSource(str(out_path))
    out_lyr = out_ds.CreateLayer("holes", geom_type=ogr.wkbPolygon)
    out_lyr.CreateField(ogr.FieldDefn("prov_adcode", ogr.OFTInteger))
    out_lyr.CreateField(ogr.FieldDefn("prov_name", ogr.OFTString))
    out_lyr.CreateField(ogr.FieldDefn("area_deg2", ogr.OFTReal))

    # 展平: GeometryCollection 可能含 LineString/Point 残留 → 只取 Polygon
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
    polys = [p for p in polys if p.area >= MIN_HOLE_AREA_DEG2 and p.is_valid]

    n_hole = 0
    total_area = 0.0
    for sub in polys:
        wb = to_wkb(sub, output_dimension=2)
        ogr_g = ogr.CreateGeometryFromWkb(wb)
        if ogr_g is None:
            continue
        f = ogr.Feature(out_lyr.GetLayerDefn())
        f.SetField("prov_adcode", PROV_ADCODE)
        f.SetField("prov_name", prov_name)
        f.SetField("area_deg2", sub.area)
        f.SetGeometry(ogr_g)
        out_lyr.CreateFeature(f)
        n_hole += 1
        total_area += sub.area
    out_ds = None

    print(f"WRITE n={n_hole} area={total_area:.4f} "
          f"file={out_path.name} "
          f"size={out_path.stat().st_size/1024/1024:.2f}MB "
          f"total={time.time()-t_total:.1f}s", flush=True)


if __name__ == "__main__":
    main()
