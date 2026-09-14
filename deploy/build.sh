#!/bin/bash
# Windows host → ARM64 Linux 静态构建 (麒麟 V10 用)
# 用法 (Git Bash): ./deploy/build.sh
set -e

cd "$(dirname "$0")/.."

OUT="bin/geocoder-linux-arm64"
echo "==> build $OUT (CGO_ENABLED=0 GOOS=linux GOARCH=arm64)"

CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build \
    -trimpath \
    -ldflags="-s -w" \
    -o "$OUT" \
    ./cmd/geocoder

echo "==> done"
ls -lh "$OUT"
file "$OUT" 2>/dev/null || echo "(跳过 file 检查)"
