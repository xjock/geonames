#!/usr/bin/env bash
# WOF country repos: whosonfirst-data-admin-{cc}
# 261 个国家, master 分支 zip, ~40GB+, 走代理
PROXY="socks5h://127.0.0.1:1080"
ROOT="D:/Dev/situation/geonames/data/wof"
LIST="/tmp/wof_countries.txt"
mkdir -p "$ROOT"

while read -r REPO; do
  CC="${REPO#whosonfirst-data-admin-}"
  OUT="$ROOT/${CC}.zip"
  if [ -f "$OUT" ] && [ "$(stat -c%s "$OUT")" -gt 50000 ]; then
    echo "  $CC skip"; continue
  fi
  URL="https://github.com/whosonfirst-data/${REPO}/archive/refs/heads/master.zip"
  echo "  $CC downloading..."
  if curl -sk --max-time 1800 -L -x "$PROXY" -o "$OUT.tmp" "$URL" 2>/dev/null && [ -s "$OUT.tmp" ]; then
    mv "$OUT.tmp" "$OUT"
    ls -lah "$OUT" | awk '{print "    "$5" "$9}'
  else
    rm -f "$OUT.tmp"
    echo "  $CC FAIL"
  fi
done < "$LIST"
echo "DONE wof"