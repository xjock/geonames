# -*- coding: utf-8 -*-
"""阶段 1: 建 poi_master / poi_name / poi_bbox_index 三表
从 geonames_loc 迁三区 (sea/afr/me) 行, 同步 geonames_alt → poi_name.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "geocoder.db"

# 三区 ISO-3166 alpha-2 → region
CC_REGION = {
    # 东南亚 (11)
    "MM": "sea", "TH": "sea", "VN": "sea", "LA": "sea", "KH": "sea",
    "MY": "sea", "SG": "sea", "ID": "sea", "PH": "sea", "BN": "sea",
    "TL": "sea",
    # 中东 (15)
    "AE": "me", "SA": "me", "IQ": "me", "IR": "me", "IL": "me",
    "JO": "me", "LB": "me", "SY": "me", "YE": "me", "OM": "me",
    "KW": "me", "BH": "me", "QA": "me", "CY": "me", "TR": "me",
    # 非洲 (54)
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
CC_FLAT = list(CC_REGION.keys())


SCHEMA = """
CREATE TABLE IF NOT EXISTS poi_master (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    region       TEXT NOT NULL,
    cc           TEXT,
    name_zh      TEXT,
    name_en      TEXT,
    name_local   TEXT,
    altnames     TEXT,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    bbox_min_lat REAL, bbox_min_lon REAL,
    bbox_max_lat REAL, bbox_max_lon REAL,
    placetype    TEXT,
    fclass       TEXT,
    fcode        TEXT,
    admin1       TEXT,
    admin2       TEXT,
    admin3       TEXT,
    admin4       TEXT,
    region_id    INTEGER REFERENCES poi_master(id),
    country_id   INTEGER REFERENCES poi_master(id),
    pop          INTEGER DEFAULT 0,
    importance   REAL DEFAULT 0,
    fetched_at   TEXT DEFAULT (datetime('now')),
    verified     INTEGER DEFAULT 0,
    notes        TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_pm_region ON poi_master(region);
CREATE INDEX IF NOT EXISTS idx_pm_cc ON poi_master(cc);
CREATE INDEX IF NOT EXISTS idx_pm_name_zh ON poi_master(name_zh COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_pm_name_en ON poi_master(name_en COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_pm_placetype ON poi_master(placetype);
CREATE INDEX IF NOT EXISTS idx_pm_country_id ON poi_master(country_id);
CREATE INDEX IF NOT EXISTS idx_pm_pop ON poi_master(pop DESC);
CREATE INDEX IF NOT EXISTS idx_pm_importance ON poi_master(importance DESC);
CREATE INDEX IF NOT EXISTS idx_pm_lat_lon ON poi_master(lat, lon);
CREATE INDEX IF NOT EXISTS idx_pm_region_cc ON poi_master(region, cc);
CREATE INDEX IF NOT EXISTS idx_pm_region_placetype ON poi_master(region, placetype);

CREATE TABLE IF NOT EXISTS poi_name (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    poi_id      INTEGER NOT NULL REFERENCES poi_master(id) ON DELETE CASCADE,
    lang        TEXT NOT NULL,
    name        TEXT NOT NULL,
    is_official INTEGER DEFAULT 0,
    source      TEXT,
    UNIQUE (poi_id, lang, source)
);
CREATE INDEX IF NOT EXISTS idx_pn_poi ON poi_name(poi_id);
CREATE INDEX IF NOT EXISTS idx_pn_lang ON poi_name(lang);

CREATE TABLE IF NOT EXISTS poi_bbox_index (
    poi_id  INTEGER PRIMARY KEY REFERENCES poi_master(id) ON DELETE CASCADE,
    min_lat REAL NOT NULL,
    min_lon REAL NOT NULL,
    max_lat REAL NOT NULL,
    max_lon REAL NOT NULL,
    region  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bbox_lat ON poi_bbox_index(min_lat, max_lat);
CREATE INDEX IF NOT EXISTS idx_bbox_lon ON poi_bbox_index(min_lon, max_lon);
CREATE INDEX IF NOT EXISTS idx_bbox_region ON poi_bbox_index(region);
"""


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()
    print("[schema] poi_master / poi_name / poi_bbox_index ready", flush=True)


def map_placetype(fclass, fcode):
    """GeoNames fclass/fcode → poi_master.placetype"""
    if fclass == "A":
        if fcode == "PCLI":
            return "country"
        if fcode in ("ADM1",):
            return "region"
        if fcode in ("ADM2", "ADM3", "ADM4"):
            return "localadmin"
        return "admin"
    if fclass == "P":
        if fcode == "PPLC":
            return "locality"
        if fcode in ("PPLA", "PPLA2", "PPLA3", "PPLA4"):
            return "locality"
        if fcode in ("PPL", "PPLC", "PPLA"):
            return "locality"
        return "poi"
    if fclass in ("S", "T", "H", "L", "U", "V", "R"):
        return "poi"
    return None


def migrate_geonames(conn):
    """从 geonames_loc + 三区 cc 过滤 → poi_master"""
    cur = conn.cursor()
    n_done = cur.execute(
        "SELECT COUNT(*) FROM poi_master WHERE source='geonames'"
    ).fetchone()[0]
    if n_done > 0 and "--redo" not in sys.argv:
        print(f"[geonames] skip: already {n_done:,} rows (use --redo to redo)",
              flush=True)
        return

    placeholders = ",".join("?" * len(CC_FLAT))
    sql = f"""
        SELECT id, name, ascii, lat, lon, fclass, fcode, cc,
               admin1, admin2, admin3, admin4, pop
        FROM geonames_loc
        WHERE cc IN ({placeholders})
          AND lat IS NOT NULL AND lon IS NOT NULL
    """
    rows = cur.execute(sql, CC_FLAT).fetchall()
    print(f"[geonames] {len(rows):,} 三区候选行", flush=True)

    BATCH = 10000
    batch = []
    n = 0
    t0 = time.time()
    for r in rows:
        gid, name, ascii_, lat, lon, fclass, fcode, cc, a1, a2, a3, a4, pop = r
        region = CC_REGION.get(cc, "global")
        ptype = map_placetype(fclass, fcode)
        imp = 0.0
        try:
            if pop and pop > 0:
                import math
                imp = min(1.0, math.log10(pop) / 7.0)
        except Exception:
            pass
        if fcode == "PPLC":
            imp = max(imp, 0.9)
        batch.append((
            "geonames", str(gid), region, cc,
            name, ascii_ or name, name,
            None,
            lat, lon, None, None, None, None,
            ptype, fclass, fcode, a1 or "", a2 or "", a3 or "", a4 or "",
            None, None,
            pop or 0, imp,
        ))
        if len(batch) >= BATCH:
            cur.executemany("""
                INSERT OR IGNORE INTO poi_master(
                    source, source_id, region, cc, name_zh, name_en, name_local,
                    altnames, lat, lon,
                    bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon,
                    placetype, fclass, fcode, admin1, admin2, admin3, admin4,
                    region_id, country_id, pop, importance
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, batch)
            conn.commit()
            n += len(batch)
            batch.clear()
            if n % 50000 == 0:
                print(f"  +{n:,} ({time.time()-t0:.0f}s)", flush=True)
    if batch:
        cur.executemany("""
            INSERT OR IGNORE INTO poi_master(
                source, source_id, region, cc, name_zh, name_en, name_local,
                altnames, lat, lon,
                bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon,
                placetype, fclass, fcode, admin1, admin2, admin3, admin4,
                region_id, country_id, pop, importance
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, batch)
        n += len(batch)
        conn.commit()
    print(f"[geonames] 迁 {n:,} 行 ({time.time()-t0:.0f}s)", flush=True)


def migrate_altnames(conn):
    """geonames_alt → poi_name"""
    cur = conn.cursor()
    n_done = cur.execute(
        "SELECT COUNT(*) FROM poi_name WHERE source='geonames'"
    ).fetchone()[0]
    if n_done > 0 and "--redo" not in sys.argv:
        print(f"[altnames] skip: already {n_done:,} rows", flush=True)
        return

    pm_ids = cur.execute(
        "SELECT id, source_id FROM poi_master WHERE source='geonames'"
    ).fetchall()
    pm_map = {int(sid): pid for pid, sid in pm_ids}
    pm_sids = set(pm_map.keys())
    print(f"[altnames] {len(pm_sids):,} geonames poi 待补 altnames", flush=True)

    if not pm_sids:
        return

    BATCH = 20000
    CHUNK = 500  # SQLite limit ~999 vars
    batch = []
    n = 0
    t0 = time.time()
    sids_list = list(pm_sids)
    for chunk_start in range(0, len(sids_list), CHUNK):
        chunk = sids_list[chunk_start:chunk_start + CHUNK]
        placeholders = ",".join("?" * len(chunk))
        sql = f"""
            SELECT geonameid, isolang, altname
            FROM geonames_alt
            WHERE geonameid IN ({placeholders})
              AND isolang IS NOT NULL AND isolang != ''
              AND altname IS NOT NULL AND altname != ''
        """
        for r in cur.execute(sql, chunk):
            gid, lang, name = r
            pid = pm_map.get(gid)
            if pid is None:
                continue
            lang_norm = lang.split("-")[0].lower()
            batch.append((pid, lang_norm, name, 0, "geonames"))
            if len(batch) >= BATCH:
                cur.executemany("""
                    INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source)
                    VALUES (?,?,?,?,?)
                """, batch)
                conn.commit()
                n += len(batch)
                batch.clear()
                if n % 200000 == 0:
                    print(f"  +{n:,} ({time.time()-t0:.0f}s)", flush=True)
    if batch:
        cur.executemany("""
            INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source)
            VALUES (?,?,?,?,?)
        """, batch)
        n += len(batch)
        conn.commit()
    print(f"[altnames] 迁 {n:,} 行 ({time.time()-t0:.0f}s)", flush=True)


def backfill_names_from_alt(conn):
    cur = conn.cursor()
    n = cur.execute("""
        UPDATE poi_master
        SET name_zh = (
            SELECT pn.name FROM poi_name pn
            WHERE pn.poi_id = poi_master.id AND pn.lang = 'zh' LIMIT 1
        )
        WHERE name_zh IS NULL OR name_zh = ''
    """).rowcount
    print(f"[name_zh] backfill {n:,} 行", flush=True)
    n = cur.execute("""
        UPDATE poi_master
        SET name_en = (
            SELECT pn.name FROM poi_name pn
            WHERE pn.poi_id = poi_master.id AND pn.lang = 'en' LIMIT 1
        )
        WHERE name_en IS NULL OR name_en = ''
    """).rowcount
    print(f"[name_en] backfill {n:,} 行", flush=True)
    conn.commit()


def fill_country_id(conn):
    cur = conn.cursor()
    n = cur.execute("""
        UPDATE poi_master
        SET country_id = (
            SELECT c.id FROM poi_master c
            WHERE c.cc = poi_master.cc AND c.fcode = 'PCLI'
            LIMIT 1
        )
        WHERE country_id IS NULL
    """).rowcount
    print(f"[country_id] fill {n:,} 行", flush=True)
    conn.commit()


def main():
    if not DB_PATH.exists():
        print(f"[err] db not found: {DB_PATH}", flush=True)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000000")

    init_schema(conn)
    migrate_geonames(conn)
    migrate_altnames(conn)
    backfill_names_from_alt(conn)
    fill_country_id(conn)
    conn.execute("ANALYZE")

    print("\n[verify]", flush=True)
    for region in ("sea", "afr", "me"):
        n = conn.execute(
            "SELECT COUNT(*) FROM poi_master WHERE region=?", (region,)
        ).fetchone()[0]
        print(f"  region={region}: {n:,}", flush=True)
    n_zh = conn.execute(
        "SELECT COUNT(*) FROM poi_master WHERE name_zh IS NOT NULL AND name_zh != ''"
    ).fetchone()[0]
    n_name = conn.execute("SELECT COUNT(*) FROM poi_name").fetchone()[0]
    print(f"  name_zh 非空: {n_zh:,}", flush=True)
    print(f"  poi_name 总行: {n_name:,}", flush=True)
    sample = conn.execute("""
        SELECT id, source, source_id, cc, name_zh, name_en, lat, lon, fcode
        FROM poi_master WHERE region='sea' AND fcode='PPLC' LIMIT 5
    """).fetchall()
    print("\n[sample sea PPLC]", flush=True)
    for r in sample:
        print(f"  {tuple(r)}", flush=True)
    sample = conn.execute("""
        SELECT id, source, source_id, cc, name_zh, name_en, lat, lon, fcode
        FROM poi_master WHERE region='afr' AND cc='NE' LIMIT 5
    """).fetchall()
    print("\n[sample afr NE]", flush=True)
    for r in sample:
        print(f"  {tuple(r)}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
