# -*- coding: utf-8 -*-
"""合并: 全部省 _holes_XX.gpkg + _holes_tdt.csv + _holes_tdt_dense.csv
-> cn_holes_tdt.gpkg (全国, 含 TDT 反查属性)
字段: adcode, prov_name, area_deg2, n_pts, has_village, villages, towns
"""
import os, sys, csv, re
os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
VB = Path("D:/Dev/situation/geonames/village-boundaries")
VRE = re.compile(r'村|社区|居委会')

attrs = {}
for csvname in ['_holes_tdt.csv', '_holes_tdt_dense.csv']:
    p = VB / csvname
    if not p.exists():
        continue
    with open(p, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            key = (r['adcode'], int(r['hole_fid']))
            cur = attrs.get(key, {'villages': set(), 'towns': set(), 'n_pts': 0})
            cur['villages'] |= set(filter(None, r['villages'].split('|')))
            cur['towns'] |= set(filter(None, r['towns'].split('|')))
            cur['n_pts'] += int(r['n_pts'])
            attrs[key] = cur

out = VB / 'cn_holes_tdt.gpkg'
if out.exists():
    out.unlink()
drv = ogr.GetDriverByName('GPKG')
ds = drv.CreateDataSource(str(out))
lyr = ds.CreateLayer('holes', geom_type=ogr.wkbPolygon)
for fn, ft in [('adcode', ogr.OFTInteger), ('prov_name', ogr.OFTString),
               ('area_deg2', ogr.OFTReal), ('n_pts', ogr.OFTInteger),
               ('has_village', ogr.OFTInteger),
               ('villages', ogr.OFTString), ('towns', ogr.OFTString)]:
    lyr.CreateField(ogr.FieldDefn(fn, ft))

n_total = n_vc = 0
for gpkg in sorted(VB.glob('_holes_*.gpkg')):
    m = re.match(r'_holes_(\d+)_([^.]+)\.gpkg', gpkg.name)
    if not m or 'villages' in gpkg.name:
        continue
    adcode = int(m.group(1)) * 10000
    src = ogr.Open(str(gpkg))
    slyr = src.GetLayer(0)
    for feat in slyr:
        key = (str(adcode), feat.GetFID())
        a = attrs.get(key, {'villages': set(), 'towns': set(), 'n_pts': 0})
        villages = '|'.join(sorted(a['villages']))[:250]
        has_vc = 1 if VRE.search(villages) else 0
        nf = ogr.Feature(lyr.GetLayerDefn())
        nf.SetField('adcode', adcode)
        nf.SetField('prov_name', m.group(2))
        nf.SetField('area_deg2', feat.GetField('area_deg2'))
        nf.SetField('n_pts', a['n_pts'])
        nf.SetField('has_village', has_vc)
        nf.SetField('villages', villages)
        nf.SetField('towns', '|'.join(sorted(a['towns']))[:250])
        nf.SetGeometry(feat.GetGeometryRef().Clone())
        lyr.CreateFeature(nf)
        n_total += 1
        n_vc += has_vc
    src = None
ds = None
print(f"wrote {n_total} holes ({n_vc} with village) -> {out} "
      f"({out.stat().st_size//1024//1024}MB)")