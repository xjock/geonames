# -*- coding: utf-8 -*-
"""下载 thedavidweng/china-village-boundaries release v2026.06 全部分省 zip。

幂等：已存在且大小匹配的跳过；大小不符的重下。用法:
    python scripts/download_village_boundaries.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

PROXY = "socks5h://127.0.0.1:1080"
API = "https://api.github.com/repos/thedavidweng/china-village-boundaries/releases/tags/v2026.06"
OUT = Path(__file__).resolve().parent.parent / "village-boundaries"

def main():
    OUT.mkdir(exist_ok=True)
    # 1) 资产清单
    ap = subprocess.run(
        ["curl", "-s", "--max-time", "30", "-x", PROXY, API],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True)
    assets = json.loads(ap.stdout)["assets"]
    total = len(assets)
    failed = []
    for i, a in enumerate(assets, 1):
        name, url, size = a["name"], a["browser_download_url"], a["size"]
        dest = OUT / name
        if dest.exists() and dest.stat().st_size == size:
            print(f"[{i}/{total}] SKIP {name} (ok)", flush=True)
            continue
        for attempt in range(3):
            print(f"[{i}/{total}] GET {name} ({size/1e6:.0f}MB) try{attempt+1}", flush=True)
            subprocess.run(
                ["curl", "-sL", "--retry", "3", "-x", PROXY,
                 "--max-time", "1800", "-o", str(dest), url])
            if dest.exists() and dest.stat().st_size == size:
                break
            print(f"  retry {name}", flush=True)
            time.sleep(5)
        else:
            failed.append(name)
            print(f"  FAIL {name}", flush=True)
    # 2) 校验
    r = subprocess.run(
        ["curl", "-sL", "-x", PROXY,
         "https://github.com/thedavidweng/china-village-boundaries/releases/download/v2026.06/SHA256SUMS.txt"],
        capture_output=True, check=True)
    (OUT / "SHA256SUMS.txt").write_bytes(r.stdout)
    chk = subprocess.run(["sha256sum", "-c", "SHA256SUMS.txt"],
                         cwd=OUT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    print(chk.stdout)
    if failed:
        print("FAILED:", failed)
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
