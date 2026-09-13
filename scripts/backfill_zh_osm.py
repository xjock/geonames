# -*- coding: utf-8 -*-
"""OSM PBF 流式抽 name:zh + 坐标, 灌 poi_master.source='osm'.
带 region/cc 自动推断 (从 PBF 文件名).
"""
import os
import sys
import time
from pathlib import Path

import osmium
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"

# 三区 ISO 国家前缀
SEA_CC = {"MM","TH","VN","LA","KH","MY","SG","ID","PH","BN","TL","CN","TW","HK","MO","NP","BT","LK","MV","PK","BD","IN"}
ME_CC  = {"AE","SA","IQ","IR","IL","JO","LB","SY","YE","OM","KW","BH","QA","CY","TR","PS"}

# 文件名 → ISO alpha-2 映射 (Geofabrik 用全名)
NAME_TO_CC = {
    "myanmar": "MM", "thailand": "TH", "vietnam": "VN", "laos": "LA",
    "cambodia": "KH", "malaysia": "MY", "singapore": "SG", "brunei": "BN",
    "indonesia": "ID", "philippines": "PH", "timor": "TL",
    "nigeria": "NG", "ghana": "GH", "kenya": "KE", "tanzania": "TZ",
    "ethiopia": "ET", "egypt": "EG", "sudan": "SD", "south": "SS",
    "congo": "CG", "angola": "AO", "algeria": "DZ", "morocco": "MA",
    "tunisia": "TN", "libya": "LY", "uganda": "UG", "zambia": "ZM",
    "zimbabwe": "ZW", "cameroon": "CM", "senegal": "SN", "mali": "ML",
    "iran": "IR", "iraq": "IQ", "saudi": "SA", "emirates": "AE",
    "israel": "IL", "jordan": "JO", "lebanon": "LB", "syria": "SY",
    "yemen": "YE", "oman": "OM", "kuwait": "KW", "bahrain": "BH",
    "qatar": "QA", "cyprus": "CY", "turkey": "TR",
}


def pbf_to_cc_region(pbf_path: Path):
    """文件名 → cc + region. 例: myanmar-latest.osm.pbf → MM/sea"""
    name = pbf_path.stem.replace("-latest.osm.pbf", "").lower()
    # 处理 "congo-democratic-republic" / "malaysia-singapore-brunei" 这类多段
    if name in NAME_TO_CC:
        cc = NAME_TO_CC[name]
    else:
        # 试首段
        first = name.split("-")[0]
        cc = NAME_TO_CC.get(first, first[:2].upper())
    if cc in SEA_CC:
        return cc, "sea"
    if cc in ME_CC:
        return cc, "me"
    return cc, "afr"


class POIHandler(osmium.SimpleHandler):
    def __init__(self, db, cc, region):
        super().__init__()
        self.db = db
        self.cc = cc
        self.region = region
        self.n = 0
        self.n_zh = 0
        self.batch = []
        self.BATCH = 5000

    def _commit(self):
        if not self.batch:
            return
        try:
            self.db.executemany("""
                INSERT INTO poi_master(source, source_id, region, cc, name_zh, name_en, name_local, lat, lon, placetype, fclass, admin1)
                VALUES ('osm', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    name_zh = CASE WHEN poi_master.name_zh IS NULL OR poi_master.name_zh = '' OR poi_master.name_zh NOT GLOB '*[一-龥]*'
                                    THEN excluded.name_zh ELSE poi_master.name_zh END,
                    name_en = CASE WHEN poi_master.name_en IS NULL OR poi_master.name_en = ''
                                    THEN excluded.name_en ELSE poi_master.name_en END,
                    name_local = CASE WHEN poi_master.name_local IS NULL OR poi_master.name_local = ''
                                    THEN excluded.name_local ELSE poi_master.name_local END
            """, self.batch)
            self.db.commit()
        except Exception as e:
            print(f"[ERR] commit: {e}", flush=True)
        self.batch = []

    def node(self, n):
        self.n += 1
        tags = n.tags
        # 仅灌行政点 (place=city/town/village/county/region/state/country/...)
        place = tags.get("place", "")
        if place not in ("city","town","village","hamlet","suburb","neighbourhood",
                         "quarter","locality","county","region","state","country",
                         "municipality","borough","city_block"):
            return
        zh = tags.get("name:zh") or tags.get("name:zh-CN") or tags.get("name:zh-Hans")
        en = tags.get("name:en")
        local = tags.get("name")
        if not (zh or en or local):
            return
        lat = n.location.lat if n.location and n.location.lat is not None else None
        lon = n.location.lon if n.location and n.location.lon is not None else None
        if lat is None or lon is None:
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return

        pt = place
        fclass = "A" if pt in ("country","region","county","state") else "P"
        admin1 = tags.get("addr:state") or tags.get("is_in:state") or ""

        sid = f"n{n.id}"
        self.batch.append((sid, self.region, self.cc, zh or "", en or "", local or "",
                           lat, lon, pt, fclass, admin1))
        if zh:
            self.n_zh += 1
        if len(self.batch) >= self.BATCH:
            self._commit()

    def flush(self):
        self._commit()


def run(pbf_path: Path):
    cc, region = pbf_to_cc_region(pbf_path)
    print(f"[osm] {pbf_path.name}  cc={cc}  region={region}  size={pbf_path.stat().st_size/1024/1024:.1f}MB")

    db = sqlite3.connect(str(DB), timeout=300)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")

    h = POIHandler(db, cc, region)
    t0 = time.time()
    try:
        osmium.apply(str(pbf_path), h)
    except Exception as e:
        print(f"[osm] err: {e}", flush=True)
    finally:
        h.flush()
        db.close()

    print(f"[osm] done  nodes={h.n:,}  with_zh={h.n_zh:,}  elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    pbfs = sys.argv[1:] or ["F:/HIAN/OSM/pbf/myanmar-latest.osm.pbf"]
    for arg in pbfs:
        path = Path(arg)
        if not path.exists():
            print(f"[skip] 缺失: {path.name}", flush=True)
            continue
        try:
            run(path)
        except Exception as e:
            print(f"[err] {path.name}: {type(e).__name__}: {e}", flush=True)
