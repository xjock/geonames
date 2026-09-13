# -*- coding: utf-8 -*-
"""批量回填: 从 geonames_alt 找汉字别名 → UPDATE poi_master.name_zh (仅 geonames 行).
不限 isolang, 直接看 altname 是否含汉字. is_preferred=1 优先.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"


def main():
    c = sqlite3.connect(str(DB), timeout=300)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")

    print("[1/3] 建映射表 (geonames 行, 缺 name_zh 真中文)")
    c.execute("DROP TABLE IF EXISTS tmp_pm_geoid")
    c.execute("CREATE TEMP TABLE tmp_pm_geoid (pm_id INT, geoid INT)")
    c.execute("CREATE INDEX tmp_idx ON tmp_pm_geoid(geoid)")
    c.execute("""
        INSERT INTO tmp_pm_geoid
        SELECT id, CAST(source_id AS INTEGER)
        FROM poi_master
        WHERE source='geonames'
          AND source_id GLOB '[0-9]*'
          AND (name_zh IS NULL OR name_zh = '' OR name_zh NOT GLOB '*[一-龥]*')
    """)
    c.commit()
    n_pm = c.execute("SELECT COUNT(*) FROM tmp_pm_geoid").fetchone()[0]
    print(f"  候选 geoid: {n_pm:,}")

    print("[2/3] 找含汉字 altname 的 alt 行")
    # JOIN 后取全部 (无 ORDER BY 提速), Python 端选优
    cur = c.execute("""
        SELECT t.pm_id, a.altname, a.isolang, a.is_preferred, a.is_short
        FROM geonames_alt a
        JOIN tmp_pm_geoid t ON t.geoid = a.geonameid
        WHERE a.altname >= char(19968)
          AND a.altname <  char(63744)
    """)
    cand = {}
    n_total = 0
    for pm_id, alt, iso, pref, short in cur:
        n_total += 1
        # 选优: iso=zh/zh-CN/zh-Hans/zh-HK/zh-SG/zh-MY 优先; is_preferred=1 优先; 否则取第一
        score = (
            (0 if iso in ("zh", "zh-CN", "zh-Hans", "zh-HK", "zh-SG", "zh-MY") else
             1 if iso in ("zh-TW", "zh-Hant", "zh-MO") else 2),
            0 if pref else 1,
            0 if short else 1,
            len(alt),  # 短名优先
        )
        prev = cand.get(pm_id)
        if prev is None or score < prev[0]:
            cand[pm_id] = (score, alt, iso, pref, short)

    print(f"  alt 行命中: {n_total:,}")
    print(f"  候选 pm 行: {len(cand):,}")

    # 排序打印前 10 (按 score)
    sorted_cand = sorted(cand.items(), key=lambda x: x[1][0])
    print("  === 前 10 条 (score 最优) ===")
    for pm_id, (score, alt, iso, pref, short) in sorted_cand[:10]:
        r = c.execute("""
            SELECT COALESCE(name_en,''), COALESCE(cc,''), COALESCE(pop,0)
            FROM poi_master WHERE id=?
        """, (pm_id,)).fetchone()
        try:
            print(f"    pm_id={pm_id:>7}  en='{r[0][:40]}'  cc={r[1]}  pop={r[2]:>9}  ->  zh='{alt}'  ({iso}, pref={pref}, short={short})")
        except UnicodeEncodeError:
            print(f"    pm_id={pm_id:>7}  en={r[0][:40]!r}  ->  zh={alt!r}")

    if "--write" not in sys.argv:
        print("\n(传 --write 才会写库)")
        c.close()
        return

    print("[3/3] UPDATE poi_master.name_zh + INSERT poi_name")
    n_upd = 0
    n_pn = 0
    BATCH = 5000
    batch = []
    for pm_id, (score, alt, iso, pref, short) in cand.items():
        batch.append((alt, pm_id, alt))
        if len(batch) >= BATCH:
            cur = c.executemany("""
                UPDATE poi_master SET name_zh = ?
                WHERE id = ? AND (name_zh IS NULL OR name_zh = ''
                    OR name_zh NOT GLOB '*[一-龥]*')
            """, [(a, pid) for a, pid, _ in batch])
            n_upd += cur.rowcount
            for pid, a in [(pid, a) for a, pid, _ in batch]:
                cur = c.execute("""
                    INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source)
                    VALUES (?, 'zh', ?, 0, 'geonames_alt')
                """, (pid, a))
                n_pn += cur.rowcount
            c.commit()
            batch = []
    if batch:
        cur = c.executemany("""
            UPDATE poi_master SET name_zh = ?
            WHERE id = ? AND (name_zh IS NULL OR name_zh = ''
                OR name_zh NOT GLOB '*[一-龥]*')
        """, [(a, pid) for a, pid, _ in batch])
        n_upd += cur.rowcount
        for pid, a in [(pid, a) for a, pid, _ in batch]:
            cur = c.execute("""
                INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source)
                VALUES (?, 'zh', ?, 0, 'geonames_alt')
            """, (pid, a))
            n_pn += cur.rowcount
        c.commit()

    print(f"  updated name_zh: {n_upd:,}")
    print(f"  inserted poi_name: {n_pn:,}")
    c.close()


if __name__ == "__main__":
    main()
