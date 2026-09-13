# -*- coding: utf-8 -*-
"""守护: 等 wikidata dump 下完 (curl 不在), 自动启 parse.
判断: dump 大小 ≥ 90GB 视为完; 或 curl 进程不在 + 文件 5min 不变.
"""
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP = Path(r"F:\HIAN\wikidata\latest-all.json.bz2")
LOG = ROOT / "logs" / "parse_wikidata.log"
PYTHON = r"C:\Python\Python312\python.exe"
SCRIPT = str(ROOT / "scripts" / "parse_wikidata_dump.py")
MIN_SIZE_GB = 90
STABLE_MINUTES = 5


def dump_size_gb():
    return DUMP.stat().st_size / 1024 / 1024 / 1024 if DUMP.exists() else 0


def curl_running():
    out = subprocess.run(
        ["powershell", "-Command", "Get-Process curl -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
        capture_output=True, text=True, timeout=10,
    )
    return bool(out.stdout.strip())


def parse_running():
    try:
        out = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe' and commandline like '%parse_wikidata_dump%'",
             "get", "processid"],
            capture_output=True, text=True, timeout=15,
        )
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip().isdigit()]
        return bool(lines)
    except Exception:
        return False


def main():
    print(f"[watch] DUMP={DUMP}")
    print(f"[watch] 阈值 ≥{MIN_SIZE_GB}GB 或 (curl 不在 + 5min 不变)")
    stable_since = None
    last_size = dump_size_gb()
    while True:
        sz = dump_size_gb()
        now = time.time()
        if abs(sz - last_size) > 0.05:
            last_size = sz
            stable_since = None
        curl_on = curl_running()
        print(f"[watch] {time.strftime('%H:%M:%S')} dump={sz:.2f}GB  curl={curl_on}  parse={parse_running()}", flush=True)

        if parse_running():
            print(f"[watch] parse 在跑, 等 5min 再 check", flush=True)
            time.sleep(300)
            continue

        if sz >= MIN_SIZE_GB:
            trigger = True
            reason = f"≥{MIN_SIZE_GB}GB"
        elif not curl_on:
            if stable_since is None:
                stable_since = now
            elif now - stable_since > STABLE_MINUTES * 60:
                trigger = True
                reason = "curl 已退 + 5min 大小不变"
            else:
                trigger = False
        else:
            trigger = False

        if trigger:
            print(f"[watch] 触发 parse: {reason}", flush=True)
            with open(LOG, "ab") as f:
                proc = subprocess.Popen(
                    [PYTHON, SCRIPT],
                    stdout=f, stderr=subprocess.STDOUT,
                    cwd=str(ROOT),
                )
            print(f"[watch] parse 启动 pid={proc.pid}, 退出 watch", flush=True)
            return

        time.sleep(60)


if __name__ == "__main__":
    main()
