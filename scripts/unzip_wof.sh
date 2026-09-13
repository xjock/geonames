#!/usr/bin/env bash
# 解压全部 WOF zip → data/wof_unzip/
ROOT="D:/Dev/situation/geonames/data"
mkdir -p "$ROOT/wof_unzip"
cd "$ROOT/wof" || exit 1
N=0
for z in *.zip; do
  if [ -d "$ROOT/wof_unzip/${z%.zip}" ]; then
    continue
  fi
  unzip -q -o "$z" -d "$ROOT/wof_unzip/" 2>&1 | head -3
  N=$((N+1))
  if [ $((N % 20)) -eq 0 ]; then
    echo "[$N] last: $z"
  fi
done
echo "DONE unzip, files: $(find $ROOT/wof_unzip -type f -name '*.geojson' | wc -l)"