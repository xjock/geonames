# -*- coding: utf-8 -*-
"""从 xzqh.org 抓取四川全省县区村级 12 位区划码表，补充 gpkg。

流程:
1. 四川省栏目页 list/10025.html 抽全部县区链接
2. 每个县区栏目页找 "行政区划" 文章链接
3. 文章页解析编码表 (12位码+城乡分类码+名称, 9位乡镇码+名称)
4. 输出 sichuan_xzqh_villages.csv
5. 回填 cn_villages_named.gpkg 四川图层: xzqh_name / xzqh_year 列

用法:
    python scripts/scrape_xzqh_sichuan.py
"""
import csv
import re
import time
import html
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = ROOT / "village-boundaries" / "sichuan_xzqh_villages.csv"
GPKG = ROOT / "village-boundaries" / "cn_villages_named.gpkg"
PROVINCE_LIST = "https://www.xzqh.org/html/list/10025.html"
PROXY = "socks5h://127.0.0.1:1080"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CACHE = ROOT / "xzqh_cache"
CACHE.mkdir(exist_ok=True)


def fetch(url: str) -> str:
    """代理 curl + GBK 解码, 本地缓存, 3 次重试"""
    key = re.sub(r"[^0-9a-zA-Z]+", "_", url)[-80:] + ".html"
    f = CACHE / key
    if f.exists() and f.stat().st_size > 1000:
        return f.read_bytes().decode("gbk", errors="replace")
    last = None
    for attempt in range(6):
        try:
            subprocess.run(
                ["curl", "-sk", "--max-time", "120", "-x", PROXY, "-A", UA, url, "-o", str(f)],
                check=True)
            break
        except subprocess.CalledProcessError as e:
            last = e
            time.sleep(min(5 * (attempt + 1), 30))
    else:
        raise last
    time.sleep(1.0)  # 礼貌延迟
    return f.read_bytes().decode("gbk", errors="replace")


def strip_tags(raw: str) -> str:
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.S)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", body))
    return re.sub(r"[ \t\r]+", " ", txt)


CITY_LISTS = [269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279, 280,
              281, 282, 283, 284, 285, 286, 287, 288, 289]  # 四川 21 市州


def county_links() -> list:
    """21 市州栏目页 -> [行政区划文章url, ...] (名称从文章 title 取, 见 main)"""
    out = []
    for cid in CITY_LISTS:
        try:
            raw = fetch(f"https://www.xzqh.org/html/list/{cid}.html")
        except Exception as e:
            print(f"city list/{cid} fetch fail: {e}; rerun to fill gap")
            continue
        for mo in re.finditer(
                r"<a[^>]+href=[\"']([^\"']*show/[^\"']+)[\"'][^>]*>[^<]*行政区划</a>",
                raw, flags=re.S):
            href = mo.group(1)
            out.append(href if href.startswith("http") else
                       ("https://www.xzqh.org" + href if href.startswith("/")
                        else "https://www.xzqh.org/html/" + href))
    return out


def division_url(county_page_url: str) -> str | None:
    """县区栏目页 -> '行政区划' 文章 url"""
    raw = fetch(county_page_url)
    for href, txt in re.findall(
            r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", raw, flags=re.S):
        name = html.unescape(re.sub(r"<[^>]+>", "", txt)).strip()
        if name == "行政区划":
            return "https://www.xzqh.org/html/" + href
    return None


def parse_division(raw: str):
    """解析编码表 -> (county, year, village_rows)"""
    m = re.search(r"<title>\s*([^_<]+?)行政区划", raw)
    county = m.group(1).strip() if m else ""
    txt = strip_tags(raw)
    m = re.search(r"(20\d\d|19\d\d)年[^ ]{0,10}行政区划", txt)
    year = m.group(1) if m else ""
    rows, cur_town = [], ""
    for line in txt.split("\n"):
        line = line.strip()
        mv = re.match(r"^(\d{12})\s+(\d{3})\s+(.+)$", line)
        if mv:
            rows.append((mv.group(1), mv.group(2), mv.group(3).strip(), cur_town, county, year))
            continue
        mt = re.match(r"^(\d{9})\s+(\D.+)$", line)
        if mt:
            cur_town = mt.group(2).strip()
    return county, year, rows


def main():
    arts = county_links()
    print(f"division articles found: {len(arts)}")
    all_rows, fail = [], []
    for i, art in enumerate(arts, 1):
        try:
            county, year, rows = parse_division(fetch(art))
            if not rows:
                fail.append((county or art, "no village rows")); continue
            all_rows.extend(rows)
            print(f"[{i}/{len(arts)}] {county} year={year} villages={len(rows)}")
        except Exception as e:
            fail.append((art, str(e)))
            print(f"[{i}/{len(arts)}] FAIL {art}: {e}")
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code12", "urban_code", "name", "town", "county", "year"])
        w.writerows(all_rows)
    print(f"\nWROTE {len(all_rows)} rows -> {OUT_CSV.name}; fail={len(fail)}")
    for n, e in fail:
        print("  FAIL:", n, e)


if __name__ == "__main__":
    main()
