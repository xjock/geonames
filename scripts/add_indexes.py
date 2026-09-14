# -*- coding: utf-8 -*-
"""新 db 缺 poi_master/poi_name 索引. 加关键查询索引."""
import sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geocoder.db"

INDEXES = [
    ('idx_pm_name_zh', 'CREATE INDEX idx_pm_name_zh ON poi_master(name_zh)'),
    ('idx_pm_name_en', 'CREATE INDEX idx_pm_name_en ON poi_master(name_en)'),
    ('idx_pm_region', 'CREATE INDEX idx_pm_region ON poi_master(region)'),
    ('idx_pm_cc', 'CREATE INDEX idx_pm_cc ON poi_master(cc)'),
    ('idx_pm_region_cc', 'CREATE INDEX idx_pm_region_cc ON poi_master(region, cc)'),
    ('idx_pm_placetype', 'CREATE INDEX idx_pm_placetype ON poi_master(placetype)'),
    ('idx_pm_pop', 'CREATE INDEX idx_pm_pop ON poi_master(pop DESC)'),
    ('idx_pm_importance', 'CREATE INDEX idx_pm_importance ON poi_master(importance DESC)'),
    ('idx_pm_lat_lon', 'CREATE INDEX idx_pm_lat_lon ON poi_master(lat, lon)'),
    ('idx_pm_country_id', 'CREATE INDEX idx_pm_country_id ON poi_master(country_id)'),
    ('idx_pn_poi_id', 'CREATE INDEX idx_pn_poi_id ON poi_name(poi_id)'),
    ('idx_pn_lang', 'CREATE INDEX idx_pn_lang ON poi_name(lang)'),
    ('idx_pn_name', 'CREATE INDEX idx_pn_name ON poi_name(name)'),
]


def main():
    db = sqlite3.connect(str(DB), timeout=600)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=-2000000")
    t0 = time.time()
    for name, sql in INDEXES:
        ts = time.time()
        print(f"[idx] {name:<25} ...", end="", flush=True)
        db.execute(sql)
        db.commit()
        print(f" {time.time()-ts:.0f}s", flush=True)
    db.close()
    print(f"\n[done] {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
