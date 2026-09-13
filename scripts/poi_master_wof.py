# -*- coding: utf-8 -*-
"""阶段 2: 从 wof_admin 迁三区 admin 行到 poi_master + poi_bbox_index.
source='wof', source_id=cast(id as text), bbox_* 来自 geom:bbox.
"""
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "geocoder.db"

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
CC_FLAT = list(CC_REGION.keys())


def map_placetype_wof(pt):
    return {
        "country": "country",
        "region": "region",
        "county": "region",
        "locality": "locality",
        "localadmin": "localadmin",
        "neighbourhood": "neighbourhood",
        "microhood": "neighbourhood",
        "macrohood": "neighbourhood",
        "borough": "borough",
        "dependency": "country",
        "disputed": "region",
        "continent": "region",
    }.get(pt, "admin")


def main():
    if not DB_PATH.exists():
        print(f"[err] db not found: {DB_PATH}", flush=True)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000000")
    cur = conn.cursor()

    n_done = cur.execute(
        "SELECT COUNT(*) FROM poi_master WHERE source='wof'"
    ).fetchone()[0]
    if "--redo" in sys.argv:
        print(f"[wof] --redo: 清旧 {n_done:,} 行", flush=True)
        cur.execute("DELETE FROM poi_master WHERE source='wof'")
        conn.commit()
    elif n_done > 0:
        print(f"[wof] skip: already {n_done:,} rows (use --redo to redo)",
              flush=True)
        return

    placeholders = ",".join("?" * len(CC_FLAT))
    sql = f"""
        SELECT id, name, cc, placetype, lat, lon,
               bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon
        FROM wof_admin
        WHERE cc IN ({placeholders})
          AND lat IS NOT NULL AND lon IS NOT NULL
    """
    print(f"[wof] streaming 三区候选行...", flush=True)

    BATCH = 10000
    pm_batch = []
    bbox_batch = []
    n_pm = 0
    n_bbox = 0
    t0 = time.time()

    cur2 = conn.cursor()
    cur2.execute(sql, CC_FLAT)
    for r in cur2:
        wid, name, cc, placetype, lat, lon, bmin_lat, bmin_lon, bmax_lat, bmax_lon = r
        region = CC_REGION.get(cc, "global")
        ptype = map_placetype_wof(placetype)
        if placetype == "country":
            imp = 0.85
        elif placetype == "region":
            imp = 0.5
        elif placetype == "locality":
            imp = 0.6
        elif placetype == "localadmin":
            imp = 0.4
        else:
            imp = 0.2

        pm_batch.append((
            "wof", str(wid), region, cc,
            None, name, name,
            None,
            lat, lon,
            bmin_lat, bmin_lon, bmax_lat, bmax_lon,
            ptype, None, None, "", "", "", "",
            None, None, 0, imp,
        ))

        if bmin_lat is not None and bmax_lat is not None:
            bbox_batch.append((wid, bmin_lat, bmin_lon, bmax_lat, bmax_lon, region))

        if len(pm_batch) >= BATCH:
            cur.executemany("""
                INSERT OR IGNORE INTO poi_master(
                    source, source_id, region, cc, name_zh, name_en, name_local,
                    altnames, lat, lon,
                    bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon,
                    placetype, fclass, fcode, admin1, admin2, admin3, admin4,
                    region_id, country_id, pop, importance
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, pm_batch)
            conn.commit()
            n_pm += len(pm_batch)
            pm_batch.clear()

            if bbox_batch:
                wid_list = [str(w) for w, *_ in bbox_batch]
                ph = ",".join("?" * len(wid_list))
                id_map = dict(cur.execute(
                    f"SELECT source_id, id FROM poi_master WHERE source='wof' AND source_id IN ({ph})",
                    wid_list
                ).fetchall())
                bb = [(id_map[str(w)], bmn_l, bmn_o, bmx_l, bmx_o, reg)
                      for w, bmn_l, bmn_o, bmx_l, bmx_o, reg in bbox_batch
                      if str(w) in id_map]
                cur.executemany("""
                    INSERT OR IGNORE INTO poi_bbox_index(poi_id, min_lat, min_lon, max_lat, max_lon, region)
                    VALUES (?,?,?,?,?,?)
                """, bb)
                conn.commit()
                n_bbox += len(bb)
                bbox_batch.clear()
            if n_pm % 50000 == 0:
                print(f"  +{n_pm:,} poi / +{n_bbox:,} bbox ({time.time()-t0:.0f}s)",
                      flush=True)

    if pm_batch:
        cur.executemany("""
            INSERT OR IGNORE INTO poi_master(
                source, source_id, region, cc, name_zh, name_en, name_local,
                altnames, lat, lon,
                bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon,
                placetype, fclass, fcode, admin1, admin2, admin3, admin4,
                region_id, country_id, pop, importance
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, pm_batch)
        n_pm += len(pm_batch)
        pm_batch.clear()

    if bbox_batch:
        ssids = list({str(w) for w, *_ in bbox_batch})
        ph = ",".join("?" * len(ssids))
        id_map = dict(cur.execute(
            f"SELECT source_id, id FROM poi_master WHERE source='wof' AND source_id IN ({ph})",
            ssids
        ).fetchall())
        bb = [(id_map[str(w)], bmn_l, bmn_o, bmx_l, bmx_o, reg)
              for w, bmn_l, bmn_o, bmx_l, bmx_o, reg in bbox_batch
              if str(w) in id_map]
        cur.executemany("""
            INSERT OR IGNORE INTO poi_bbox_index(poi_id, min_lat, min_lon, max_lat, max_lon, region)
            VALUES (?,?,?,?,?,?)
        """, bb)
        n_bbox += len(bb)
    conn.commit()
    print(f"[wof] DONE poi={n_pm:,} bbox={n_bbox:,} ({time.time()-t0:.0f}s)",
          flush=True)

    n = cur.execute("""
        UPDATE poi_master SET country_id = (
            SELECT c.id FROM poi_master c
            WHERE c.cc = poi_master.cc AND c.fcode = 'PCLI' LIMIT 1
        )
        WHERE source = 'wof' AND country_id IS NULL
    """).rowcount
    print(f"[country_id] backfill wof: {n:,}", flush=True)
    conn.commit()
    conn.execute("ANALYZE")

    print("\n[verify]", flush=True)
    for region in ("sea", "afr", "me"):
        n = conn.execute(
            "SELECT COUNT(*) FROM poi_master WHERE source='wof' AND region=?",
            (region,)
        ).fetchone()[0]
        print(f"  wof region={region}: {n:,}", flush=True)
    n_bbox = conn.execute("SELECT COUNT(*) FROM poi_bbox_index").fetchone()[0]
    print(f"  poi_bbox_index 总行: {n_bbox:,}", flush=True)
    sample = conn.execute("""
        SELECT pm.id, pm.source, pm.source_id, pm.cc, pm.name_en, pm.lat, pm.lon,
               pm.placetype, pm.bbox_min_lat, pm.bbox_max_lat
        FROM poi_master pm
        WHERE pm.source='wof' AND pm.cc='NE' AND pm.placetype='country'
        LIMIT 3
    """).fetchall()
    print("\n[sample wof NE country]", flush=True)
    for r in sample:
        print(f"  {tuple(r)}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
