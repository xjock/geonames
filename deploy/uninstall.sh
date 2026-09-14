#!/bin/bash
# 卸载 geocoder (保留 db 数据)
# 用法: sudo ./uninstall.sh [--purge]
set -e

SERVICE_NAME="geocoder"
APP_DIR="/opt/geocoder"
DATA_DIR="/var/lib/geocoder"
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

# 删 app + 用户
rm -rf "$APP_DIR"
if id "$APP_USER" &>/dev/null; then
    userdel "$APP_USER" 2>/dev/null || true
fi

# 数据
if [ "$1" = "--purge" ]; then
    rm -rf "$DATA_DIR"
    echo "[purge] $DATA_DIR 已删"
else
    echo "[keep]  $DATA_DIR 保留 (--purge 才删)"
fi

echo "==== 卸载完成 ===="
