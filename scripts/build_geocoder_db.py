# -*- coding: utf-8 -*-
"""灌 SQLite (SpatiaLite + FTS5) geocoder.db:
- geonames_loc: 主表 (id PK, name, ascii, lat, lon, fclass, fcode, cc, admin1..4, pop)
- geonames_alt: 别名 (geonameid, isolang, altname, flags)
- geonames_hier: 层级 (child_id, parent_id, type)
- geonames_fts: FTS5 虚表 (name + ascii + altnames 聚合)
- wof_admin: WOF admin 多边形 (id, name, cc, placetype, lat/lon, bbox, geom_wkt)
- cn_villages: 中国增强 (code12, name, lat, lon)
"""
import csv
import glob
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "geocoder.db"
CN_CSV = ROOT / "village-boundaries" / "cn_villages_named.csv"
WOF_DIR = DATA / "wof_unzip"
BATCH = 50000


def init_db():
    # 不擦库: 增量构建; --reset 才删
    if "--reset" in sys.argv:
        DB_PATH.unlink(missing_ok=True)
        print("  --reset: db wiped")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000000")

    try:
        conn.enable_load_extension(True)
        for ep in ("mod_spatialite", "mod_spatialite.dylib", "spatialite"):
            try:
                conn.load_extension(ep)
                print(f"  spatialite loaded: {ep}")
                break
            except sqlite3.OperationalError:
                continue
    except Exception as e:
        print(f"  spatialite NOT available ({e}); fall back to B-tree bbox")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS geonames_loc (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            ascii TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            fclass TEXT,
            fcode TEXT,
            cc TEXT,
            admin1 TEXT,
            admin2 TEXT,
            admin3 TEXT,
            admin4 TEXT,
            pop INTEGER DEFAULT 0,
            elevation INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_loc_fclass ON geonames_loc(fclass);
        CREATE INDEX IF NOT EXISTS idx_loc_cc ON geonames_loc(cc);
        CREATE INDEX IF NOT EXISTS idx_loc_name ON geonames_loc(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_loc_pop ON geonames_loc(pop DESC);

        CREATE TABLE IF NOT EXISTS geonames_alt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            geonameid INTEGER NOT NULL,
            isolang TEXT,
            altname TEXT NOT NULL,
            is_preferred INTEGER DEFAULT 0,
            is_short INTEGER DEFAULT 0,
            is_colloquial INTEGER DEFAULT 0,
            is_historic INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_alt_geonameid ON geonames_alt(geonameid);
        CREATE INDEX IF NOT EXISTS idx_alt_altname ON geonames_alt(altname COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_alt_iso ON geonames_alt(isolang);

        CREATE TABLE IF NOT EXISTS geonames_hier (
            child_id INTEGER NOT NULL,
            parent_id INTEGER NOT NULL,
            type TEXT,
            PRIMARY KEY (child_id, parent_id, type)
        );
        CREATE INDEX IF NOT EXISTS idx_hier_parent ON geonames_hier(parent_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS geonames_fts USING fts5(
            name, ascii, altnames,
            content='', tokenize='unicode61 remove_diacritics 2'
        );

        CREATE TABLE IF NOT EXISTS cn_villages (
            code12 TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            lat REAL,
            lon REAL,
            src_province TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cn_name ON cn_villages(name COLLATE NOCASE);

        CREATE TABLE IF NOT EXISTS wof_admin (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            cc TEXT,
            placetype TEXT,
            country_id INTEGER,
            region_id INTEGER,
            locality_id INTEGER,
            lat REAL,
            lon REAL,
            bbox_min_lat REAL,
            bbox_min_lon REAL,
            bbox_max_lat REAL,
            bbox_max_lon REAL,
            geom_wkt TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_wof_name ON wof_admin(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_wof_cc ON wof_admin(cc);
        CREATE INDEX IF NOT EXISTS idx_wof_placetype ON wof_admin(placetype);
        CREATE INDEX IF NOT EXISTS idx_wof_bbox ON wof_admin(bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon);
    """)
    conn.commit()
    return conn


def load_geonames_loc(conn):
    f = DATA / "allCountries.txt"
    print(f"[loc] {f.name} ...")
    t0 = time.time()
    n = 0
    cur = conn.cursor()
    rows = []
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 18:
                continue
            try:
                gid = int(parts[0])
                lat = float(parts[4])
                lon = float(parts[5])
            except (ValueError, IndexError):
                continue
            rows.append((
                gid, parts[1], parts[2] or parts[1], lat, lon,
                parts[6], parts[7], parts[8], parts[10], parts[11], parts[12], parts[13],
                int(parts[14]) if parts[14] else 0,
                int(parts[15]) if parts[15] else None,
            ))
            n += 1
            if len(rows) >= BATCH:
                cur.executemany(
                    "INSERT OR REPLACE INTO geonames_loc VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows)
                conn.commit()
                rows.clear()
                if n % 500000 == 0:
                    print(f"  {n:,} rows ({time.time()-t0:.0f}s)")
    if rows:
        cur.executemany(
            "INSERT OR REPLACE INTO geonames_loc VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows)
        conn.commit()
    print(f"[loc] DONE {n:,} rows in {time.time()-t0:.0f}s")


def load_alternames(conn):
    f = DATA / "alternateNamesV2.txt"
    print(f"[alt] {f.name} ...")
    t0 = time.time()
    n = 0
    rows = []
    cur = conn.cursor()
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            try:
                gid = int(parts[1])
            except ValueError:
                continue
            rows.append((
                gid, parts[2] or "", parts[3],
                int(parts[4]) if len(parts) > 4 and parts[4] else 0,
                int(parts[5]) if len(parts) > 5 and parts[5] else 0,
                int(parts[6]) if len(parts) > 6 and parts[6] else 0,
                int(parts[7]) if len(parts) > 7 and parts[7] else 0,
            ))
            n += 1
            if len(rows) >= BATCH:
                cur.executemany(
                    "INSERT OR IGNORE INTO geonames_alt(geonameid,isolang,altname,is_preferred,is_short,is_colloquial,is_historic) VALUES(?,?,?,?,?,?,?)",
                    rows)
                conn.commit()
                rows.clear()
                if n % 1000000 == 0:
                    print(f"  {n:,} rows ({time.time()-t0:.0f}s)")
    if rows:
        cur.executemany(
            "INSERT OR IGNORE INTO geonames_alt(geonameid,isolang,altname,is_preferred,is_short,is_colloquial,is_historic) VALUES(?,?,?,?,?,?,?)",
            rows)
        conn.commit()
    print(f"[alt] DONE {n:,} rows in {time.time()-t0:.0f}s")


def load_hierarchy(conn):
    f = DATA / "hierarchy.txt"
    print(f"[hier] {f.name} ...")
    t0 = time.time()
    n = 0
    rows = []
    cur = conn.cursor()
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            try:
                cid = int(parts[0])
                pid = int(parts[1])
            except ValueError:
                continue
            rows.append((cid, pid, parts[2] or ""))
            n += 1
            if len(rows) >= BATCH:
                cur.executemany("INSERT OR IGNORE INTO geonames_hier VALUES(?,?,?)", rows)
                conn.commit()
                rows.clear()
    if rows:
        cur.executemany("INSERT OR IGNORE INTO geonames_hier VALUES(?,?,?)", rows)
        conn.commit()
    print(f"[hier] DONE {n:,} rows in {time.time()-t0:.0f}s")


def build_fts(conn):
    print("[fts] building FTS5 from geonames_loc+alt ...")
    t0 = time.time()
    print("  aggregating alts ...")
    conn.execute("""
        CREATE TEMP TABLE _loc_fts_src AS
        SELECT l.id, l.name, l.ascii,
               GROUP_CONCAT(a.altname, '|') AS altnames
        FROM geonames_loc l
        LEFT JOIN geonames_alt a ON a.geonameid = l.id
        GROUP BY l.id
    """)
    print(f"  aggregated ({time.time()-t0:.0f}s)")
    t1 = time.time()
    conn.execute("""
        INSERT INTO geonames_fts(rowid, name, ascii, altnames)
        SELECT id, name, ascii, altnames FROM _loc_fts_src
    """)
    conn.commit()
    print(f"[fts] DONE insert ({time.time()-t1:.0f}s)")


def load_cn_villages(conn):
    if not CN_CSV.exists():
        print("[cn] SKIP (csv missing)")
        return
    print(f"[cn] {CN_CSV.name} ...")
    t0 = time.time()
    n = 0
    rows = []
    cur = conn.cursor()
    with open(CN_CSV, encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        for p in r:
            code = p.get("code12", "")
            name = p.get("official_name") or p.get("shp_name") or ""
            if not code or not name or name == "nan":
                continue
            rows.append((code, name, None, None, p.get("src_province", "")))
            n += 1
            if len(rows) >= BATCH:
                cur.executemany("INSERT OR REPLACE INTO cn_villages VALUES(?,?,?,?,?)", rows)
                conn.commit()
                rows.clear()
                if n % 200000 == 0:
                    print(f"  {n:,} rows ({time.time()-t0:.0f}s)")
    if rows:
        cur.executemany("INSERT OR REPLACE INTO cn_villages VALUES(?,?,?,?,?)", rows)
        conn.commit()
    print(f"[cn] DONE {n:,} rows in {time.time()-t0:.0f}s")


def load_wof_admin(conn):
    """直接从 WOF zip 读 geojson, 不需要 unzip.
    zip 结构: data/{id_num_path}/{id}.geojson, 含 -alt- 文件需过滤.
    """
    import zipfile
    WOF_ZIPS = DATA / "wof"
    if not WOF_ZIPS.exists():
        print("[wof] SKIP (zips dir missing)")
        return
    print(f"[wof] streaming from {WOF_ZIPS}/*.zip ...")
    t0 = time.time()
    n = 0
    cur = conn.cursor()
    rows = []
    zips = sorted(WOF_ZIPS.glob("*.zip"))
    print(f"  zips: {len(zips)}")
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                members = [n for n in zf.namelist() if n.endswith(".geojson") and "-alt-" not in n]
                for m in members:
                    try:
                        with zf.open(m) as fh:
                            d = json.load(fh)
                    except Exception:
                        continue
                    props = d.get("properties") or {}
                    if d.get("type") != "Feature":
                        continue
                    wid = props.get("wof:id") or d.get("id")
                    if not wid:
                        continue
                    placetype = props.get("wof:placetype", "")
                    if placetype not in ("country", "region", "locality", "localadmin", "neighbourhood",
                                          "microhood", "macrohood", "borough", "county", "dependency",
                                          "disputed", "continent"):
                        continue
                    name = props.get("wof:name") or ""
                    if not name:
                        continue
                    cc = props.get("iso:country") or props.get("wof:country") or ""
                    lat = props.get("geom:latitude")
                    lon = props.get("geom:longitude")
                    bbox = props.get("geom:bbox") or d.get("bbox") or []
                    if bbox and len(bbox) == 4:
                        bmin_lon, bmin_lat, bmax_lon, bmax_lat = bbox
                    else:
                        bmin_lon = bmin_lat = bmax_lon = bmax_lat = None
                    hier = props.get("wof:hierarchy") or [{}]
                    h0 = hier[0] if hier else {}
                    country_id = h0.get("country_id")
                    region_id = h0.get("region_id")
                    locality_id = h0.get("locality_id")
                    geom = d.get("geometry") or {}
                    geom_wkt = ""
                    if geom.get("type") == "MultiPolygon":
                        polys = geom.get("coordinates") or []
                        if polys:
                            rings = []
                            for poly in polys[:1]:
                                if poly and poly[0]:
                                    rings.append(poly[0])
                            if rings:
                                parts = ",".join(
                                    f"{' '.join(f'{x} {y}' for x, y in ring)}"
                                    for ring in rings)
                                geom_wkt = f"MULTIPOLYGON((({parts})))"
                    elif geom.get("type") == "Polygon":
                        coords = geom.get("coordinates") or []
                        if coords and coords[0]:
                            pts = " ".join(f"{x} {y}" for x, y in coords[0])
                            geom_wkt = f"POLYGON(({pts})))"
                    rows.append((
                        wid, name, cc, placetype,
                        country_id, region_id, locality_id,
                        lat, lon,
                        bmin_lat, bmin_lon, bmax_lat, bmax_lon,
                        geom_wkt,
                    ))
                    n += 1
                    if len(rows) >= 5000:
                        cur.executemany(
                            "INSERT OR REPLACE INTO wof_admin VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            rows)
                        conn.commit()
                        rows.clear()
                        if n % 50000 == 0:
                            print(f"  {n:,} rows ({time.time()-t0:.0f}s, last zip: {zp.name})")
        except Exception as e:
            print(f"  ERR {zp.name}: {e}")
            continue
        print(f"  [done zip: {zp.name} {n:,} rows {time.time()-t0:.0f}s]")
    if rows:
        cur.executemany(
            "INSERT OR REPLACE INTO wof_admin VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows)
        conn.commit()
    print(f"[wof] DONE {n:,} rows in {time.time()-t0:.0f}s")


def main():
    t0 = time.time()
    conn = init_db()
    if "--skip-loc" not in sys.argv:
        load_geonames_loc(conn)
    if "--skip-alt" not in sys.argv:
        load_alternames(conn)
    if "--skip-hier" not in sys.argv:
        load_hierarchy(conn)
    if "--skip-fts" not in sys.argv:
        build_fts(conn)
    if "--skip-cn" not in sys.argv:
        load_cn_villages(conn)
    if "--skip-wof" not in sys.argv:
        load_wof_admin(conn)
    conn.execute("ANALYZE")
    print(f"\nALL DONE {time.time()-t0:.0f}s -> {DB_PATH}")


if __name__ == "__main__":
    main()