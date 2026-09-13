# -*- coding: utf-8 -*-
"""守护 parse_wikidata_dump.py 进程.
若 parse 死 (bz2 EOF/异常), 等 60s 后重启. dump 已下完, 不会 IO hang.
parse 累计 ~50-80M entity, 估 8h 跑完.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "parse_wikidata.log"
PYTHON = r"C:\Python\Python312\python.exe"
SCRIPT = str(ROOT / "scripts" / "parse_wikidata_dump.py")


def parse_pids():
    try:
        out = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe' and commandline like '%parse_wikidata_dump%'",
             "get", "processid"],
            capture_output=True, text=True, timeout=15,
        )
        return [int(l.strip()) for l in out.stdout.splitlines() if l.strip().isdigit()]
    except Exception as e:
        print(f"[watch] wmic err: {e}", flush=True)
        return []


def spawn_parse():
    f = open(LOG, "ab")
    p = subprocess.Popen(
        [PYTHON, SCRIPT],
        stdout=f, stderr=subprocess.STDOUT,
        cwd=str(ROOT),
    )
    print(f"[watch] spawned parse pid={p.pid}", flush=True)
    return p.pid


def main():
    print(f"[watch] 监控 {SCRIPT}", flush=True)
    while True:
        pids = parse_pids()
        print(f"[watch] {time.strftime('%H:%M:%S')} parse pids={pids}", flush=True)
        if not pids:
            print(f"[watch] parse 不在, 重启", flush=True)
            spawn_parse()
            time.sleep(120)
            continue
        try:
            sz = LOG.stat().st_size
            print(f"[watch] log size={sz}", flush=True)
        except Exception:
            pass
        time.sleep(300)


if __name__ == "__main__":
    main()
