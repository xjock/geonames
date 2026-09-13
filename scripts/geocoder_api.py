# -*- coding: utf-8 -*-
"""FastAPI geocode/reverse service on SQLite geocoder.db
- GET /geocode?q=&limit=            名称 → 候选坐标 (FTS5 + GeoNames + WOF + CN boost)
- GET /reverse?lon=&lat=             坐标 → 行政区/最近点 (WOF bbox + GeoNames haversine + CN village)
- GET /health
"""
import math
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "geocoder.db"

app = FastAPI(title="Geocoder", version="0.1")


def get_conn():
    if not DB_PATH.exists():
        raise HTTPException(503, f"db not built: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


CONN = get_conn()


@app.get("/health")
def health():
    n_loc = CONN.execute("SELECT COUNT(*) FROM geonames_loc").fetchone()[0]
    n_alt = CONN.execute("SELECT COUNT(*) FROM geonames_alt").fetchone()[0]
    n_wof = CONN.execute("SELECT COUNT(*) FROM wof_admin").fetchone()[0]
    n_cn = CONN.execute("SELECT COUNT(*) FROM cn_villages").fetchone()[0]
    return {
        "db": str(DB_PATH),
        "geonames_loc": n_loc,
        "geonames_alt": n_alt,
        "wof_admin": n_wof,
        "cn_villages": n_cn,
    }


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@app.get("/geocode")
def geocode(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=50),
    cc: str | None = Query(None, max_length=2),
):
    """FTS5 优先, 命中 → 加 GeoNames 主表 + WOF admin 候选"""
    t0 = time.time()
    results = []

    # 0) 精确名匹配 (LIKE) → 最高优先级
    if cc:
        exact_rows = CONN.execute(
            "SELECT id, name, ascii, lat, lon, fclass, fcode, cc, admin1, admin2, pop "
            "FROM geonames_loc WHERE name = ? COLLATE NOCASE AND cc = ? "
            "ORDER BY pop DESC LIMIT ?",
            (q, cc, limit)).fetchall()
    else:
        exact_rows = CONN.execute(
            "SELECT id, name, ascii, lat, lon, fclass, fcode, cc, admin1, admin2, pop "
            "FROM geonames_loc WHERE name = ? COLLATE NOCASE "
            "ORDER BY pop DESC LIMIT ?",
            (q, limit)).fetchall()
    for r in exact_rows:
        results.append({
            "source": "geonames", "id": r["id"], "name": r["name"],
            "ascii": r["ascii"], "lat": r["lat"], "lon": r["lon"],
            "fclass": r["fclass"], "fcode": r["fcode"], "cc": r["cc"],
            "admin1": r["admin1"], "admin2": r["admin2"], "pop": r["pop"],
            "score": 1.0,
        })

    # 1) CN boost (中文名优先)
    if any('一' <= c <= '鿿' for c in q):
        rows = CONN.execute(
            "SELECT code12, name, lat, lon, src_province FROM cn_villages "
            "WHERE name LIKE ? OR name LIKE ? LIMIT ?",
            (q, q + "%", limit)).fetchall()
        for r in rows:
            results.append({
                "source": "cn_villages",
                "id": r["code12"],
                "name": r["name"],
                "lat": r["lat"],
                "lon": r["lon"],
                "cc": "CN",
                "admin": r["src_province"],
                "score": 1.0,
            })

    # 2) FTS5 GeoNames
    try:
        fts_q = q.replace('"', '""')
        fts_rows = CONN.execute(
            "SELECT rowid FROM geonames_fts WHERE geonames_fts MATCH ? LIMIT ?",
            (f'"{fts_q}"*', limit * 3)).fetchall()
        if fts_rows:
            ids = [r["rowid"] for r in fts_rows]
            placeholders = ",".join("?" * len(ids))
            if cc:
                sql = (f"SELECT id, name, ascii, lat, lon, fclass, fcode, cc, "
                       f"admin1, admin2, pop FROM geonames_loc "
                       f"WHERE id IN ({placeholders}) AND cc = ? "
                       f"ORDER BY CASE WHEN lower(name)=lower(?) THEN 0 ELSE 1 END, "
                       f"pop DESC LIMIT ?")
                params = list(ids) + [cc, q, limit]
            else:
                sql = (f"SELECT id, name, ascii, lat, lon, fclass, fcode, cc, "
                       f"admin1, admin2, pop FROM geonames_loc "
                       f"WHERE id IN ({placeholders}) "
                       f"ORDER BY CASE WHEN lower(name)=lower(?) THEN 0 ELSE 1 END, "
                       f"pop DESC LIMIT ?")
                params = list(ids) + [q, limit]
            loc_rows = CONN.execute(sql, params).fetchall()
            for r in loc_rows:
                results.append({
                    "source": "geonames",
                    "id": r["id"],
                    "name": r["name"],
                    "ascii": r["ascii"],
                    "lat": r["lat"],
                    "lon": r["lon"],
                    "fclass": r["fclass"],
                    "fcode": r["fcode"],
                    "cc": r["cc"],
                    "admin1": r["admin1"],
                    "admin2": r["admin2"],
                    "pop": r["pop"],
                    "score": 1.0 if r["name"].lower() == q.lower() else 0.9,
                })
    except Exception as e:
        results.append({"fts_error": str(e)})

    # 3) WOF admin
    wof_rows = CONN.execute(
        "SELECT id, name, cc, placetype, lat, lon FROM wof_admin "
        "WHERE name LIKE ? COLLATE NOCASE "
        "ORDER BY CASE placetype WHEN 'country' THEN 1 WHEN 'region' THEN 2 "
        "WHEN 'locality' THEN 3 WHEN 'localadmin' THEN 4 ELSE 5 END "
        "LIMIT ?",
        (q + "%", limit)).fetchall() if all(ord(c) < 128 for c in q) else []
    for r in wof_rows:
        results.append({
            "source": "wof",
            "id": r["id"],
            "name": r["name"],
            "cc": r["cc"],
            "placetype": r["placetype"],
            "lat": r["lat"],
            "lon": r["lon"],
            "score": 0.85,
        })

    seen = set()
    deduped = []
    for r in results:
        if "name" not in r or "lat" not in r:
            continue
        if r["lat"] is None or r["lon"] is None:
            continue
        key = (r["name"], round(r["lat"], 4), round(r["lon"], 4))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # 4) 天地图 fallback: 中文查询空时调用, 命中回灌本地库
    has_cjk = any(0x4E00 <= ord(c) <= 0x9FFF for c in q)
    if not deduped and has_cjk:
        try:
            import os as _os, urllib.request, urllib.parse, json as _json
            TDT_KEY = _os.environ.get("TDT_KEY", "fbaf76f74a84bc0daa3334dae5d36412")
            post = '{"keyWord":"%s","level":12,"mapBound":"-180,-90,180,90","queryType":1,"start":0,"count":%d}' % (
                q.replace('"', '\\"'), limit)
            url = "https://api.tianditu.gov.cn/v2/search?postStr=%s&type=query&tk=%s" % (
                urllib.parse.quote(post), TDT_KEY)
            req = urllib.request.Request(url, headers={"User-Agent": "geocoder/0.1"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                d = _json.loads(resp.read())
            # v2 search returns area{} + prompt[] + resultType=3 = POI list
            pois = []
            area = d.get("area")
            if area and area.get("lonlat"):
                ll = area["lonlat"].split(",")
                if len(ll) == 2:
                    pois.append({
                        "name": area.get("name", q),
                        "lon": float(ll[0]),
                        "lat": float(ll[1]),
                        "address": area.get("adminName", ""),
                        "type": "ADM",
                        "uid": area.get("adminCode"),
                    })
            for it in (d.get("pois") or d.get("prompt") or [])[:limit]:
                ll = it.get("lonlat")
                if ll and "," in str(ll):
                    p = ll.split(",")
                    if len(p) == 2:
                        try:
                            it["lon"], it["lat"] = float(p[0]), float(p[1])
                        except (TypeError, ValueError):
                            continue
                pois.append({
                    "name": it.get("name") or q,
                    "lat": it.get("lat"),
                    "lon": it.get("lon"),
                    "address": it.get("adminName") or it.get("address") or "",
                    "type": it.get("type") or "",
                    "uid": it.get("uid") or it.get("adminCode"),
                })
            for it in pois[:limit]:
                lat2, lon2 = it.get("lat"), it.get("lon")
                try:
                    lat2, lon2 = float(lat2), float(lon2)
                except (TypeError, ValueError):
                    continue
                nm = it.get("name") or q
                addr = it.get("address") or ""
                fcode = it.get("type") or ""
                uid = it.get("uid")
                # 回灌本地: 用负 id 段避撞 geonames 13M+ ids
                gid = None
                if uid is not None:
                    try:
                        uid_int = int(uid) if str(uid).isdigit() else abs(hash(str(uid))) % 999999999
                    except (TypeError, ValueError):
                        uid_int = abs(hash(str(uid))) % 999999999
                    gid = -(uid_int % 1000000 + 100000000)
                if gid is not None:
                    try:
                        CONN.execute(
                            "INSERT OR IGNORE INTO geonames_loc"
                            "(id,name,ascii,lat,lon,fclass,fcode,cc,admin1,admin2,pop) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (gid, nm, nm, lat2, lon2, "P", str(fcode)[:20] or "PPL",
                             "CN", "", "", 0))
                        if nm != q:
                            CONN.execute(
                                "INSERT OR IGNORE INTO geonames_alt"
                                "(geonameid,isolang,altname) VALUES(?,?,?)",
                                (gid, "zh", q))
                        CONN.execute(
                            "INSERT OR IGNORE INTO geonames_fts(rowid,name,ascii,altnames) "
                            "VALUES(?,?,?,?)",
                            (gid, nm, nm, q))
                    except Exception:
                        pass
                results.append({
                    "source": "tianditu",
                    "id": uid,
                    "name": nm,
                    "lat": lat2,
                    "lon": lon2,
                    "cc": "CN",
                    "admin": addr,
                    "fclass": str(fcode),
                    "score": 0.95,
                })
            try:
                CONN.commit()
            except Exception:
                pass
        except Exception as e:
            results.append({"tdt_error": str(e)})

    seen = set()
    deduped = []
    for r in results:
        if "name" not in r or "lat" not in r:
            continue
        if r["lat"] is None or r["lon"] is None:
            continue
        key = (r["name"], round(r["lat"], 4), round(r["lon"], 4))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return {
        "q": q,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "count": len(deduped[:limit]),
        "results": deduped[:limit],
    }


@app.get("/reverse")
def reverse(
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    radius_m: int = Query(5000, ge=100, le=50000),
):
    """坐标 → WOF admin (bbox) + 最近的 GeoNames 点 + 中国村级"""
    t0 = time.time()
    out = {"lon": lon, "lat": lat, "admin": [], "nearest": None}

    wof_rows = CONN.execute(
        "SELECT id, name, cc, placetype, lat, lon FROM wof_admin "
        "WHERE bbox_min_lat IS NOT NULL "
        "AND bbox_min_lat <= ? AND bbox_max_lat >= ? "
        "AND bbox_min_lon <= ? AND bbox_max_lon >= ? "
        "LIMIT 20",
        (lat, lat, lon, lon)).fetchall()
    admin_chain = []
    for r in wof_rows:
        d = _haversine(lat, lon, r["lat"] or 0, r["lon"] or 0) if r["lat"] else None
        admin_chain.append({
            "id": r["id"],
            "name": r["name"],
            "cc": r["cc"],
            "placetype": r["placetype"],
            "dist_m": int(d) if d else None,
        })
    prio = {"country": 1, "region": 2, "county": 3, "localadmin": 4,
            "locality": 5, "borough": 6, "neighbourhood": 7,
            "microhood": 8, "macrohood": 9}
    admin_chain.sort(key=lambda x: prio.get(x["placetype"], 99))
    out["admin"] = admin_chain[:6]

    deg_pad = radius_m / 111000.0
    rows = CONN.execute(
        "SELECT id, name, ascii, lat, lon, fclass, fcode, cc, pop FROM geonames_loc "
        "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
        "ORDER BY (lat-?)*(lat-?) + (lon-?)*(lon-?) LIMIT 1",
        (lat - deg_pad, lat + deg_pad, lon - deg_pad, lon + deg_pad,
         lat, lat, lon, lon)).fetchall()
    if rows:
        r = rows[0]
        d = _haversine(lat, lon, r["lat"], r["lon"])
        if d <= radius_m:
            out["nearest"] = {
                "id": r["id"],
                "name": r["name"],
                "ascii": r["ascii"],
                "lat": r["lat"],
                "lon": r["lon"],
                "fclass": r["fclass"],
                "fcode": r["fcode"],
                "cc": r["cc"],
                "pop": r["pop"],
                "dist_m": int(d),
            }

    out["elapsed_ms"] = int((time.time() - t0) * 1000)
    return out


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)