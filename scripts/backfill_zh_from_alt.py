# -*- coding: utf-8 -*-
"""干跑: 算 geonames 源 POI 缺中文 & alt 表有中文 的精确数 + 写库候选.
JOIN 用 INTEGER 化: CREATE TEMP TABLE tmp_pm_geoid(id INT, geoid INT) 索引后 JOIN.
不写库, 仅 print 统计 + 前 10 条样例.
"""
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"


def main():
    c = sqlite3.connect(str(DB), timeout=120)
    print("[1/4] 建临时映射 (geoid INT -> pm_id INT, 仅 geonames 行)")
    c.execute("DROP TABLE IF EXISTS tmp_pm_geoid")
    c.execute("CREATE TEMP TABLE tmp_pm_geoid (pm_id INT, geoid INT, pop INT)")
    c.execute("CREATE INDEX tmp_pm_geoid_idx ON tmp_pm_geoid(geoid)")
    c.execute("""
        INSERT INTO tmp_pm_geoid
        SELECT id, CAST(source_id AS INTEGER), COALESCE(pop, 0)
        FROM poi_master
        WHERE source='geonames'
          AND source_id GLOB '[0-9]*'
          AND lat IS NOT NULL AND lon IS NOT NULL
    """)
    c.commit()
    n_pm = c.execute("SELECT COUNT(*) FROM tmp_pm_geoid").fetchone()[0]
    print(f"  tmp_pm_geoid: {n_pm:,}")

    print("[2/4] 缺中文行数 (pm.name_zh 空/无汉字)")
    n_no_zh = c.execute("""
        SELECT COUNT(*) FROM tmp_pm_geoid t
        JOIN poi_master pm ON pm.id = t.pm_id
        WHERE pm.name_zh IS NULL OR pm.name_zh = ''
           OR pm.name_zh NOT GLOB '*[一-龥]*'
    """).fetchone()[0]
    print(f"  pm 缺 name_zh 真中文: {n_no_zh:,}")

    print("[3/4] alt 表 zh* isolang 行 (限这 geoid 子集)")
    rows = c.execute("""
        SELECT a.geonameid, a.isolang, a.altname, a.is_preferred
        FROM geonames_alt a
        JOIN tmp_pm_geoid t ON t.geoid = a.geonameid
        JOIN poi_master pm ON pm.id = t.pm_id
        WHERE a.isolang LIKE 'zh%'
          AND (pm.name_zh IS NULL OR pm.name_zh = ''
               OR pm.name_zh NOT GLOB '*[一-龥]*')
    """)
    iso_cnt = Counter()
    pm2cand = {}
    for geoid, iso, name, pref in rows:
        iso_cnt[iso] += 1
        pm2cand.setdefault(geoid, []).append((iso, name, pref))
    print(f"  alt 命中候选 pm 行: {len(pm2cand):,}")
    print(f"  按 isolang:")
    for iso, n in iso_cnt.most_common():
        print(f"    {iso:<12s} {n:>10,}")

    print("[4/4] 模拟最终选用: is_preferred=1 优先 zh/zh-Hans, 否则取第一行 zh")
    chosen = {}
    for geoid, cands in pm2cand.items():
        cands.sort(key=lambda x: (0 if x[2] else 1,
                                  0 if x[0] in ("zh", "zh-CN", "zh-Hans") else 1))
        chosen[geoid] = cands[0]
    print(f"  最终选用候选: {len(chosen):,}")

    print("\n=== 前 10 条样例 ===")
    for geoid, (iso, name, pref) in list(chosen.items())[:10]:
        r = c.execute("""
            SELECT pm.id, pm.source_id, COALESCE(pm.name_en,''),
                   COALESCE(pm.cc,''), COALESCE(pm.pop,0)
            FROM tmp_pm_geoid t JOIN poi_master pm ON pm.id = t.pm_id
            WHERE t.geoid = ?
        """, (geoid,)).fetchone()
        print(f"  pm_id={r[0]:>7} geoid={r[1]:>10} cc={r[3]} pop={r[4]:>9} "
              f"en='{r[2][:40]}' -> {iso}='{name}' pref={pref}")

    # 写库: UPDATE poi_master.name_zh (限 geonames 行, 仅当前缺中文的)
    if "--write" in sys.argv:
        print("\n[WRITE] UPDATE poi_master.name_zh")
        updated = 0
        for geoid, (iso, name, pref) in chosen.items():
            cur = c.execute("""
                UPDATE poi_master
                SET name_zh = ?
                WHERE id = (SELECT pm_id FROM tmp_pm_geoid WHERE geoid = ?)
                  AND source = 'geonames'
                  AND (name_zh IS NULL OR name_zh = ''
                       OR name_zh NOT GLOB '*[一-龥]*')
            """, (name, geoid))
            updated += cur.rowcount
            # 同步 poi_name lang='zh'
            cur = c.execute("""
                INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source)
                SELECT pm_id, 'zh', ?, 0, 'geonames_alt'
                FROM tmp_pm_geoid WHERE geoid = ?
            """, (name, geoid))
        c.commit()
        print(f"  updated: {updated}")
    else:
        print("\n(传 --write 才会写库)")

    c.close()


if __name__ == "__main__":
    main()
