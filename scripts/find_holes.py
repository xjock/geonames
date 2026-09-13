# -*- coding: utf-8 -*-
"""按省找中国国土空洞 (orchestrator + subprocess 版):

调用 scripts/run_one_prov.py 一省一次, timeout=600s (大省可调到 1800s).
失败省记 skip_*.log, 不影响其他省.

跳过: 65 新疆 / 54 西藏 / 15 内蒙 / 63 青海 (用户) + 81 港 / 82 澳
"""
import os, sys, time, csv, json, subprocess
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
VB = ROOT / "village-boundaries"
SCRIPT = ROOT / "scripts" / "run_one_prov.py"
SRC_DATAV_JSON = VB / "_datav_china.json"
DST_DIR = VB

SKIP_CODES = {65, 54, 15, 63, 81, 82}
TIMEOUT_S = 1800  # 30min / 省 (山东 85k poly)


def main():
    with open(SRC_DATAV_JSON, encoding='utf-8') as f:
        data = json.load(f)
    provinces = []
    for feat in data['features']:
        p = feat['properties']
        try:
            ac = int(p.get('adcode', 0))
        except (TypeError, ValueError):
            continue
        if ac == 0:
            continue
        prov_code = ac // 10000
        if prov_code in SKIP_CODES:
            continue
        nm = p.get('name', '')
        provinces.append((ac, prov_code, nm))
    print(f"queue {len(provinces)} provinces "
          f"(skip {sorted(SKIP_CODES)})", flush=True)

    summary = []
    t_total = time.time()
    n_done = 0
    n_fail = 0

    for adcode, prov_code, name in provinces:
        t0 = time.time()
        out_path = DST_DIR / f"_holes_{prov_code:02d}_{name}.gpkg"
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"  [SKIP] {name} ({adcode}) already exists "
                  f"({out_path.stat().st_size/1024/1024:.1f}MB)",
                  flush=True)
            n_done += 1
            summary.append({
                "adcode": adcode, "name": name,
                "n_holes": -1, "area_deg2": 0.0,
                "size_mb": round(out_path.stat().st_size / 1024 / 1024, 2),
                "el_s": 0.0,
            })
            continue
        log_path = DST_DIR / f"_run_{prov_code:02d}_{name}.log"
        try:
            with open(log_path, 'w', encoding='utf-8') as lf:
                r = subprocess.run([
                    sys.executable, str(SCRIPT), str(adcode),
                ], stdout=lf, stderr=subprocess.STDOUT,
                   timeout=TIMEOUT_S)
            elapsed = time.time() - t0
            stdout = log_path.read_text(encoding='utf-8',
                                        errors='replace')
            if r.returncode != 0:
                print(f"  [FAIL] {name} ({adcode}) rc={r.returncode} "
                      f"el={elapsed:.0f}s", flush=True)
                n_fail += 1
                continue
            # 解析 WRITE n=... area=...
            n_hole, area, sz_mb = 0, 0.0, 0.0
            for line in stdout.splitlines():
                if line.startswith("READ "):
                    print(f"  [{name}] {line} el={elapsed:.0f}s",
                          flush=True)
                elif line.startswith("WRITE "):
                    # WRITE n=N area=A file=... size=XMB total=T
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "n=": n_hole = int(parts[i+1])
                        elif p == "area=": area = float(parts[i+1])
                        elif p == "size=":
                            sz_mb = float(parts[i+1].rstrip("MB"))
                elif line.startswith("UNION ") or line.startswith("DIFF "):
                    print(f"  [{name}] {line}", flush=True)
            summary.append({
                "adcode": adcode, "name": name,
                "n_holes": n_hole, "area_deg2": round(area, 4),
                "size_mb": round(sz_mb, 2),
                "el_s": round(elapsed, 1),
            })
            print(f"  [OK]   {name:6s} ({adcode:06d})  "
                  f"holes={n_hole:5d}  area={area:.3f} deg²  "
                  f"{sz_mb:.1f}MB  el={elapsed:.0f}s",
                  flush=True)
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] {name} ({adcode}) >{TIMEOUT_S}s",
                  flush=True)
            n_fail += 1
        except Exception as e:
            print(f"  [ERR] {name} ({adcode}): {e}", flush=True)
            n_fail += 1

        n_done += 1
        # 写 summary 增量
        with open(DST_DIR / "_holes_summary.csv", "w",
                  encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["adcode", "name", "n_holes",
                        "hole_area_deg2", "size_mb", "el_s"])
            for r in sorted(summary, key=lambda x: -x["area_deg2"]):
                w.writerow([r["adcode"], r["name"], r["n_holes"],
                            r["area_deg2"], r["size_mb"], r["el_s"]])

    print(f"\nDONE done={n_done} fail={n_fail} "
          f"el={time.time()-t_total:.0f}s", flush=True)


if __name__ == "__main__":
    main()
