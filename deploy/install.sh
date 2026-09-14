#!/bin/bash
# 麒麟 V10 SP1/SP2/SP3 (aarch64) 部署 geocoder
# 用法: sudo ./install.sh
# 默认装到 /tools/sdb/data/world/names/ (与 db 共目录)
set -e

APP_USER="geocoder"
DATA_DIR="/tools/sdb/data/world/names"
SERVICE_NAME="geocoder"
LISTEN_ADDR="0.0.0.0:8000"
BIN_SRC="$(dirname "$(readlink -f "$0")")/../bin/geocoder-linux-arm64"

# 1. 检查 root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: 必须用 root 跑 (sudo $0)"
    exit 1
fi

# 2. 检查二进制
if [ ! -f "$BIN_SRC" ]; then
    echo "ERROR: 找不到 $BIN_SRC"
    echo "  先在 Windows 编: CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -ldflags='-s -w' -o bin/geocoder-linux-arm64 ./cmd/geocoder"
    exit 1
fi

# 3. 建用户 (无登录 shell)
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$DATA_DIR" "$APP_USER"
fi

# 4. 确保 DATA_DIR 存在且 geocoder 用户可读
if [ ! -d "$DATA_DIR" ]; then
    echo "ERROR: $DATA_DIR 不存在"
    echo "  调整 DATA_DIR 环境变量或手动 mkdir"
    exit 1
fi
# 父目录链 geocoder 用户 traverse 权限
DIR="$DATA_DIR"
while [ "$DIR" != "/" ]; do
    DIR="$(dirname "$DIR")"
    [ -d "$DIR" ] || break
    PERM=$(stat -c '%a' "$DIR")
    if [ $((PERM & 5)) -eq 5 ]; then
        : # world rx 已有
    else
        chmod o+rx "$DIR"
        echo "[chmod] o+rx $DIR"
    fi
done

# 5. 拷二进制 (与 db 共目录)
cp "$BIN_SRC" "$DATA_DIR/geocoder"
chmod 755 "$DATA_DIR/geocoder"
chown "$APP_USER:$APP_USER" "$DATA_DIR/geocoder"

# 6. db 文件: 若 DATA_DIR 无, 从源码 data/ 拷
if [ ! -f "$DATA_DIR/geocoder.db" ]; then
    SRC_DB="$(dirname "$(readlink -f "$0")")/../data/geocoder.db"
    if [ -f "$SRC_DB" ]; then
        cp "$SRC_DB" "$DATA_DIR/geocoder.db"
        chown "$APP_USER:$APP_USER" "$DATA_DIR/geocoder.db"
        chmod 644 "$DATA_DIR/geocoder.db"
        echo "[db] copied from $SRC_DB"
    else
        echo "WARN: $DATA_DIR/geocoder.db 不存在, 启动后 /health 会显示 0 行"
        echo "  手动拷: scp data/geocoder.db root@host:$DATA_DIR/"
    fi
else
    chmod 644 "$DATA_DIR/geocoder.db"
    chown "$APP_USER:$APP_USER" "$DATA_DIR/geocoder.db"
fi

# 7. systemd 单元
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Geocoder (POI search/reverse API)
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${DATA_DIR}
ExecStart=${DATA_DIR}/geocoder --addr ${LISTEN_ADDR} --db ${DATA_DIR}/geocoder.db
Restart=on-failure
RestartSec=5
LimitNOFILE=65535

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=${DATA_DIR}

[Install]
WantedBy=multi-user.target
EOF

# 8. 启用 + 启动
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

sleep 2
systemctl status "$SERVICE_NAME" --no-pager || true

echo ""
echo "==== 部署完成 ===="
echo "数据/二进制: ${DATA_DIR}"
echo "服务:        systemctl {start|stop|status|restart} ${SERVICE_NAME}"
echo "日志:        journalctl -u ${SERVICE_NAME} -f"
echo "健康检查:    curl http://127.0.0.1:${LISTEN_ADDR##*:}/health"
echo "测试:        curl 'http://127.0.0.1:${LISTEN_ADDR##*:}/geocode?q=马六甲&limit=3'"
