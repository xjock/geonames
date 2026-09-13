# -*- coding: utf-8 -*-
"""批量导出: 每省含村/社区命中的洞 -> _holes_XX_<省名>_villages.gpkg
字段: fid, area_deg2, villages, towns
"""
import os, sys, csv, re
os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
VB = Path("D:/Dev/situation/geonames/village-boundaries")
VRE = re.compile(r'村|社区|居委会')

# adcode -> hits
hits = {}
with open(VB / '_holes_tdt.csv', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if r['villages'] and VRE.search(r['villages']):
            hits.setdefault(r['adcode'], {})[int(r['hole_fid'])] = (r['villages'], r['towns'])

for gpkg in sorted(VB.glob('_holes_*.gpkg')):
    m = re.match(r'_holes_(\d+)_([^.]+)\.gpkg', gpkg.name)
    if not m or 'villages' in gpkg.name:
        continue
    adcode = str(int(m.group(1)) * 10000)
    h = hits.get(adcode)
    if not h:
        continue
    src = ogr.Open(str(gpkg))
    slyr = src.GetLayer(0)
    out = VB / f"_holes_{m.group(1)}_{m.group(2)}_villages.gpkg"
    if out.exists():
        out.unlink()
    ds = ogr.GetDriverByName('GPKG').CreateDataSource(str(out))
    lyr = ds.CreateLayer('holes_with_villages', geom_type=ogr.wkbPolygon)
    for fn, ft in [('fid', ogr.OFTInteger), ('area_deg2', ogr.OFTReal),
                   ('villages', ogr.OFTString), ('towns', ogr.OFTString)]:
        lyr.CreateField(ogr.FieldDefn(fn, ft))
    n = 0
    for feat in slyr:
        fid = feat.GetFID()
        if fid not in h:
            continue
        nf = ogr.Feature(lyr.GetLayerDefn())
        nf.SetField('fid', fid)
        nf.SetField('area_deg2', feat.GetField('area_deg2'))
        nf.SetField('villages', h[fid][0][:250])
        nf.SetField('towns', h[fid][1][:250])
        nf.SetGeometry(feat.GetGeometryRef().Clone())
        lyr.CreateFeature(nf)
        n += 1
    ds = None; src = None
    print(f"{m.group(2)}: {n} holes -> {out.name} ({out.stat().st_size//1024}KB)")
print("DONE")