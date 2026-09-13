# -*- coding: utf-8 -*-
"""把 cn_holes_tdt.gpkg (1007 村洞) 追加进 cn_villages.gpkg villages 层.
映射: official_name=第一个村名, shp_name=全部村名(|分隔),
      src_layer='tdt_holes', src_province=拼音, code12 空.
"""
import os, sys
os.environ['PATH'] = 'D:/Dev/toolchain/libmapping-1.0.0/bin;' + os.environ.get('PATH', '')
os.environ.setdefault('SHAPE_ENCODING', 'GBK')
from osgeo import ogr
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
VB = Path("D:/Dev/situation/geonames/village-boundaries")

PINYIN = {
    '北京市': 'beijing', '天津市': 'tianjin', '河北省': 'hebei',
    '山西省': 'shanxi', '内蒙古自治区': 'neimenggu', '辽宁省': 'liaoning',
    '吉林省': 'jilin', '黑龙江省': 'heilongjiang', '上海市': 'shanghai',
    '江苏省': 'jiangsu', '浙江省': 'zhejiang', '安徽省': 'anhui',
    '福建省': 'fujian', '江西省': 'jiangxi', '山东省': 'shandong',
    '河南省': 'henan', '湖北省': 'hubei', '湖南省': 'hunan',
    '广东省': 'guangdong', '广西壮族自治区': 'guangxi', '海南省': 'hainan',
    '重庆市': 'chongqing', '四川省': 'sichuan', '贵州省': 'guizhou',
    '云南省': 'yunnan', '西藏自治区': 'xizang', '陕西省': 'shaanxi',
    '甘肃省': 'gansu', '青海省': 'qinghai', '宁夏回族自治区': 'ningxia',
    '新疆维吾尔自治区': 'xinjiang', '台湾省': 'taiwan',
}

src = ogr.Open(str(VB / 'cn_holes_tdt.gpkg'))
slyr = src.GetLayer(0)
dst = ogr.Open(str(VB / 'cn_villages.gpkg'), update=1)
dlyr = dst.GetLayer(0)
defn = dlyr.GetLayerDefn()

n = 0
dlyr.StartTransaction()
for f in slyr:
    g = f.GetGeometryRef()
    if g is None or g.IsEmpty():
        continue
    g = g.Clone()
    if g.GetGeometryName() == 'POLYGON':
        mp = ogr.Geometry(ogr.wkbMultiPolygon)
        mp.AddGeometry(g)
        g = mp
    villages = (f.GetField('villages') or '').strip()
    first = villages.split('|')[0] if villages else ''
    env = g.GetEnvelope()  # (minx, maxx, miny, maxy)
    nf = ogr.Feature(defn)
    nf.SetField('code12', '')
    nf.SetField('official_name', first)
    nf.SetField('shp_name', villages[:250])
    nf.SetField('src_province', PINYIN.get(f.GetField('prov_name') or '', ''))
    nf.SetField('src_layer', 'tdt_holes')
    nf.SetField('src_encoding', '')
    nf.SetField('min_lon', env[0])
    nf.SetField('max_lon', env[1])
    nf.SetField('min_lat', env[2])
    nf.SetField('max_lat', env[3])
    nf.SetGeometry(g)
    dlyr.CreateFeature(nf)
    n += 1
dlyr.CommitTransaction()
print(f"appended {n}")
src = None
dst = None
print("DONE")