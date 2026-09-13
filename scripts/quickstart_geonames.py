# -*- coding: utf-8 -*-
"""GeoNames quickstart: stream allCountries.zip, filter + query without loading into RAM.

Fields (tab-separated, see http://download.geonames.org/export/dump/readme.txt):
 0 geonameid        1 name            2 asciiname       3 alternatenames
 4 latitude         5 longitude       6 feature_class   7 feature_code
 8 country_code     9 cc2             10 admin1_code     11 admin2_code
 12 admin3_code      13 admin4_code     14 population      15 elevation
 16 dem              17 timezone        18 modification_date

feature_class 关键值:
  P = 居民点(城市/村镇)   A = 行政区   S = 设施(机场/学校...)
  T = 地形(山/湖)         H = 水体     L = 区域/公园
"""
import csv
import sys
import zipfile
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "allCountries.zip"

def iter_rows():
    with zipfile.ZipFile(DATA) as z:
        with z.open("allCountries.txt") as f:
            for row in csv.reader((line.decode("utf-8") for line in f), delimiter="\t"):
                yield row

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"

    if mode == "demo":
        # 中国人口最多的 10 个城市 (feature_class=P, country=CN)
        rows = (r for r in iter_rows()
                if r[6] == "P" and r[8] == "CN" and r[14].isdigit())
        top = sorted(rows, key=lambda r: int(r[14]), reverse=True)[:10]
        for r in top:
            print(f"{r[1]:<12} lat={r[4]:>8} lng={r[5]:>9} pop={int(r[14]):>10,} admin1={r[10]}")

    elif mode == "nearby":
        # 用法: python quickstart_geonames.py nearby <lat> <lng> <km>
        lat, lng, km = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
        # 粗略方形预筛 + 精确 haversine
        import math
        dlat = km / 111.0
        dlng = km / (111.0 * math.cos(math.radians(lat)))
        out = []
        for r in iter_rows():
            if not r[4] or not r[14].isdigit():
                continue
            la, lo = float(r[4]), float(r[5])
            if abs(la - lat) > dlat or abs(lo - lng) > dlng:
                continue
            p1, p2 = math.radians(la), math.radians(lat)
            dp, dl = math.radians(la - lat), math.radians(lo - lng)
            h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
            dist = 6371.0 * 2 * math.asin(math.sqrt(h))
            if dist <= km and int(r[14]) > 0:
                out.append((dist, r[1], r[8], int(r[14])))
        for d, name, cc, pop in sorted(out)[:20]:
            print(f"{d:6.1f} km  {name:<25} {cc}  pop={pop:,}")

    elif mode == "export":
        # 导出子集为 CSV: python quickstart_geonames.py export CN out.csv
        cc, outpath = sys.argv[2], Path(sys.argv[3])
        n = 0
        with open(outpath, "w", encoding="utf-8", newline="") as w:
            wr = csv.writer(w)
            for r in iter_rows():
                if r[8] == cc:
                    wr.writerow([r[0], r[1], r[4], r[5], r[6], r[7], r[10], r[14]])
                    n += 1
        print(f"{n} rows -> {outpath}")

if __name__ == "__main__":
    main()
