# -*- coding: utf-8 -*-
"""阶段 3: osmium 流式解析 PBF → poi_master + poi_name.
PBF 来源 F:/HIAN/OSM/pbf/*-latest.osm.pbf, 三区 cc 过滤.
"""
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "geocoder.db"
PBF_ROOT = Path("F:\\HIAN\\OSM\\pbf")

CC_REGION = {
    "MM": "sea", "TH": "sea", "VN": "sea", "LA": "sea", "KH": "sea",
    "MY": "sea", "SG": "sea", "ID": "sea", "PH": "sea", "BN": "sea",
    "TL": "sea",
    "AE": "me", "SA": "me", "IQ": "me", "IR": "me", "IL": "me",
    "JO": "me", "LB": "me", "SY": "me", "YE": "me", "OM": "me",
    "KW": "me", "BH": "me", "QA": "me", "CY": "me", "TR": "me",
    "DZ": "afr", "AO": "afr", "BJ": "afr", "BW": "afr", "BF": "afr",
    "BI": "afr", "CV": "afr", "CM": "afr", "CF": "afr", "TD": "afr",
    "KM": "afr", "CG": "afr", "CD": "afr", "CI": "afr", "DJ": "afr",
    "EG": "afr", "GQ": "afr", "ER": "afr", "SZ": "afr", "ET": "afr",
    "GA": "afr", "GM": "afr", "GH": "afr", "GN": "afr", "GW": "afr",
    "KE": "afr", "LS": "afr", "LR": "afr", "LY": "afr", "MG": "afr",
    "MW": "afr", "ML": "afr", "MR": "afr", "MU": "afr", "MA": "afr",
    "MZ": "afr", "NA": "afr", "NE": "afr", "NG": "afr", "RW": "afr",
    "ST": "afr", "SN": "afr", "SC": "afr", "SL": "afr", "SO": "afr",
    "ZA": "afr", "SS": "afr", "SD": "afr", "TZ": "afr", "TG": "afr",
    "TN": "afr", "UG": "afr", "ZM": "afr", "ZW": "afr",
}


def collect_pbfs():
    """扫 PBF_ROOT, 按文件名匹配三区"""
    if not PBF_ROOT.exists():
        return []
    # Geofabrik 文件名 → ISO 映射 (三区限定)
    NAME2CC = {
        # SEA (11)
        "myanmar": "MM", "thailand": "TH", "vietnam": "VN",
        "laos": "LA", "cambodia": "KH", "malaysia": "MY",
        "malaysia-singapore-brunei": "MY",
        "singapore": "SG", "indonesia": "ID", "philippines": "PH",
        "brunei": "BN", "timor-leste": "TL", "east-timor": "TL",
        # ME (15)
        "united-arab-emirates": "AE", "saudi-arabia": "SA",
        "gcc-states": "SA",
        "iraq": "IQ", "iran": "IR", "israel-and-palestine": "IL",
        "israel": "IL", "palestine": "PS",
        "jordan": "JO", "lebanon": "LB", "syria": "SY",
        "yemen": "YE", "oman": "OM", "kuwait": "KW",
        "bahrain": "BH", "qatar": "QA", "cyprus": "CY",
        "turkey": "TR",
        # AFR (54)
        "algeria": "DZ", "angola": "AO", "benin": "BJ",
        "botswana": "BW", "burkina-faso": "BF", "burundi": "BI",
        "cape-verde": "CV", "cameroon": "CM",
        "central-african-republic": "CF", "chad": "TD",
        "comores": "KM", "congo-brazzaville": "CG",
        "congo-democratic-republic": "CD",
        "ivory-coast": "CI", "cote-divoire": "CI",
        "djibouti": "DJ", "egypt": "EG",
        "equatorial-guinea": "GQ", "eritrea": "ER",
        "eswatini": "SZ", "swaziland": "SZ",
        "ethiopia": "ET", "gabon": "GA", "gambia": "GM",
        "ghana": "GH", "guinea": "GN", "guinea-bissau": "GW",
        "kenya": "KE", "lesotho": "LS", "liberia": "LR",
        "libya": "LY", "madagascar": "MG", "malawi": "MW",
        "mali": "ML", "mauritania": "MR", "mauritius": "MU",
        "morocco": "MA", "mozambique": "MZ", "namibia": "NA",
        "niger": "NE", "nigeria": "NG", "rwanda": "RW",
        "sao-tome-and-principe": "ST", "senegal": "SN",
        "senegal-and-gambia": "SN",
        "seychelles": "SC", "sierra-leone": "SL",
        "somalia": "SO", "south-africa": "ZA",
        "south-sudan": "SS", "sudan": "SD", "tanzania": "TZ",
        "togo": "TG", "tunisia": "TN", "uganda": "UG",
        "zambia": "ZM", "zimbabwe": "ZW",
    }
    pbfs = []
    for pbf in PBF_ROOT.rglob("*-latest.osm.pbf"):
        # "east-timor-latest.osm.pbf" → stem = "east-timor-latest.osm" → strip "latest.osm"
        stem = pbf.stem.lower()
        if stem.endswith("-latest.osm"):
            stem = stem[:-len("-latest.osm")]
        elif stem.endswith("-latest"):
            stem = stem[:-len("-latest")]
        cc = NAME2CC.get(stem)
        cc = NAME2CC.get(stem)
        if cc in CC_REGION:
            pbfs.append((pbf, cc))
    return pbfs


def map_placetype_osm(place_tag):
    return {
        "country": "country",
        "state": "region", "province": "region", "region": "region",
        "county": "localadmin",
        "city": "locality", "town": "locality",
        "village": "locality", "hamlet": "locality",
        "suburb": "borough", "neighbourhood": "neighbourhood",
    }.get(place_tag, "poi")


def main():
    if not DB_PATH.exists():
        print(f"[err] db not found: {DB_PATH}", flush=True)
        sys.exit(1)

    try:
        import osmium
    except ImportError:
        print("[err] pip install osmium", flush=True)
        sys.exit(1)

    class POIHandler(osmium.SimpleHandler):
        def __init__(self, conn, cc, region):
            super().__init__()
            self.conn = conn
            self.cc = cc
            self.region = region
            self.batch = []
            self.BATCH = 5000
            self.n = 0
            self.t0 = time.time()
            self.n_skip = 0

        def node(self, n):
            if not n.location.valid():
                return
            t = n.tags
            name_zh = t.get("name:zh") or t.get("name:zh-CN") or t.get("name:zh-Hans")
            name_en = t.get("name:en")
            name_local = t.get("name")
            if not (name_local or name_en or name_zh):
                self.n_skip += 1
                return
            place = t.get("place") or ""
            ptype = map_placetype_osm(place)
            pop_str = t.get("population")
            try:
                pop = int(pop_str) if pop_str else 0
            except ValueError:
                pop = 0
            lat = float(n.location.lat)
            lon = float(n.location.lon)
            source_id = f"n{n.id}"
            self.batch.append(("osm", source_id, self.region, self.cc,
                               name_zh, name_en, name_local, None,
                               lat, lon, None, None, None, None,
                               ptype, None, place or None,
                               "", "", "", "",
                               None, None, pop, 0.0))
            for lang_tag, lang_code in (
                ("name:zh", "zh"), ("name:en", "en"),
                ("name:th", "th"), ("name:vi", "vi"),
                ("name:my", "my"), ("name:km", "km"),
                ("name:lo", "lo"), ("name:id", "id"),
                ("name:ms", "ms"), ("name:tl", "tl"),
                ("name:ar", "ar"), ("name:fa", "fa"),
                ("name:he", "he"), ("name:tr", "tr"),
                ("name:fr", "fr"), ("name:sw", "sw"),
            ):
                v = t.get(lang_tag)
                if v:
                    self.batch.append(("__name__", source_id, lang_code, v))
            if len(self.batch) >= self.BATCH:
                self._flush()

        def _flush(self):
            if not self.batch:
                return
            cur = self.conn.cursor()
            pm_rows = [b for b in self.batch if b[0] == "osm"]
            name_rows = [b for b in self.batch if b[0] == "__name__"]
            self.batch.clear()
            if pm_rows:
                cur.executemany("""
                    INSERT OR IGNORE INTO poi_master(
                        source, source_id, region, cc, name_zh, name_en, name_local,
                        altnames, lat, lon,
                        bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon,
                        placetype, fclass, fcode, admin1, admin2, admin3, admin4,
                        region_id, country_id, pop, importance
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, pm_rows)
            if name_rows:
                ssids = list({r[1] for r in name_rows})
                B = 500
                all_pn = []
                for c0 in range(0, len(ssids), B):
                    chunk = ssids[c0:c0 + B]
                    ph = ",".join("?" * len(chunk))
                    id_map = dict(cur.execute(
                        f"SELECT source_id, id FROM poi_master WHERE source='osm' AND source_id IN ({ph})",
                        chunk
                    ).fetchall())
                    all_pn.extend(
                        (id_map[sid], lang, nm, 0, "osm")
                        for _, sid, lang, nm in name_rows if sid in id_map
                    )
                if all_pn:
                    cur.executemany("""
                        INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source)
                        VALUES (?,?,?,?,?)
                    """, all_pn)
            self.conn.commit()
            self.n += len(pm_rows)
            if self.n % 50000 == 0:
                print(f"  [{self.cc}] +{self.n:,} poi / skip {self.n_skip:,} no-name ({time.time()-self.t0:.0f}s)",
                      flush=True)

    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000000")

    pbfs = collect_pbfs()
    if not pbfs:
        print(f"[err] no PBFs found under {PBF_ROOT}", flush=True)
        return
    cc_filter = None
    if "--cc" in sys.argv:
        i = sys.argv.index("--cc")
        if i + 1 < len(sys.argv):
            cc_filter = sys.argv[i + 1].upper()
            pbfs = [(p, c) for p, c in pbfs if c == cc_filter]
            print(f"[osm] --cc={cc_filter} 过滤后 {len(pbfs)} PBF", flush=True)
    if not pbfs:
        print(f"[err] --cc={cc_filter} 无匹配 PBF", flush=True)
        return
    print(f"[osm] {len(pbfs)} PBFs 命中三区", flush=True)
    for pbf, cc in pbfs:
        print(f"\n[osm] === {cc} {pbf.name} ===", flush=True)
        h = POIHandler(conn, cc, CC_REGION[cc])
        try:
            h.apply_file(str(pbf), locations=True)
        except Exception as e:
            print(f"  ERR {pbf.name}: {e}", flush=True)
            continue
        h._flush()
        print(f"  [done {cc}] {h.n:,} poi", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
