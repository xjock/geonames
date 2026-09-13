# -*- coding: utf-8 -*-
"""独立 wof 灌库: 只依赖现有 db, INSERT OR REPLACE 幂等"""
import json
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "geocoder.db"
WOF_ZIPS = ROOT / "data" / "wof"
BATCH = 5000
ALLOWED = {"country", "region", "locality", "localadmin", "neighbourhood",
           "microhood", "macrohood", "borough", "county", "dependency",
           "disputed", "continent"}


def main():
    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000000")
    cur = conn.cursor()

    cur.execute("SELECT MAX(id) FROM wof_admin")
    max_id = cur.fetchone()[0] or 0
    print(f"[resume] wof max id = {max_id}", flush=True)

    zips = sorted([z for z in WOF_ZIPS.glob("*.zip")
                   if z.stat().st_size > 50000])
    state = ROOT / "data" / "wof_done.txt"
    done = set()
    if state.exists() and "--redo" not in sys.argv:
        done = set(state.read_text().splitlines())
    pending = [z for z in zips if z.stem not in done]
    print(f"[wof] {len(zips)} zips, {len(done)} done, {len(pending)} pending",
          flush=True)
    t0 = time.time()
    n = 0
    n_new = 0
    rows = []
    for zp in pending:
        try:
            with zipfile.ZipFile(zp) as zf:
                members = [m for m in zf.namelist()
                           if m.endswith(".geojson") and "-alt-" not in m]
                for m in members:
                    try:
                        with zf.open(m) as fh:
                            d = json.load(fh)
                    except Exception:
                        continue
                    if d.get("type") != "Feature":
                        continue
                    props = d.get("properties") or {}
                    wid = props.get("wof:id") or d.get("id")
                    if not wid:
                        continue
                    placetype = props.get("wof:placetype", "")
                    if placetype not in ALLOWED:
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
                        h0.get("country_id"), h0.get("region_id"), h0.get("locality_id"),
                        lat, lon,
                        bmin_lat, bmin_lon, bmax_lat, bmax_lon,
                        geom_wkt,
                    ))
                    n += 1
                    n_new += 1
                    if len(rows) >= BATCH:
                        cur.executemany(
                            "INSERT OR REPLACE INTO wof_admin VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            rows)
                        conn.commit()
                        rows.clear()
                        if n_new % 25000 == 0:
                            print(f"  +{n_new:,} rows ({time.time()-t0:.0f}s, {zp.name})",
                                  flush=True)
        except Exception as e:
            print(f"  ERR {zp.name}: {e}", flush=True)
            continue
        if rows:
            cur.executemany(
                "INSERT OR REPLACE INTO wof_admin VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows)
            conn.commit()
            rows.clear()
        print(f"  [done zip: {zp.name} +{n_new:,} rows {time.time()-t0:.0f}s]", flush=True)
        with state.open("a") as f:
            f.write(zp.stem + "\n")
    if rows:
        cur.executemany(
            "INSERT OR REPLACE INTO wof_admin VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows)
        conn.commit()
    conn.execute("ANALYZE")
    print(f"[wof] DONE n={n:,} new={n_new:,} {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
