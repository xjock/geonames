#!/bin/bash
# 卸载 geocoder (默认保留 db 数据)
# 用法: sudo ./uninstall.sh [--purge]
set -e

SERVICE_NAME="geocoder"
DATA_DIR="/tools/sdb/data/world/names"
APP_USER="geocoder"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: 必须用 root 跑"
    exit 1
fi

# 停 + 禁用服务
if systemctl list-unit-files "${SERVICE_NAME}.service" &>/dev/null; then
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
fi

# 删二进制 (DATA_DIR 其它文件不动)
rm -f "$DATA_DIR/geocoder"
echo "[clean] $DATA_DIR/geocoder removed"

# 数据
if [ "$1" = "--purge" ]; then
    rm -f "$DATA_DIR/geocoder.db" "$DATA_DIR/geocoder.db-shm" "$DATA_DIR/geocoder.db-wal"
    echo "[purge] $DATA_DIR/geocoder.db* removed"
else
    echo "[keep]  $DATA_DIR/geocoder.db 保留 (--purge 才删)"
fi

# 用户
if id "$APP_USER" &>/dev/null; then
    userdel "$APP_USER" 2>/dev/null || true
fi

echo "==== 卸载完成 ===="
