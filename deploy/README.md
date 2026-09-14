# 麒麟 V10 (aarch64) 部署

## 一次性构建 (Windows host)

```bash
./deploy/build.sh
```

输出: `bin/geocoder-linux-arm64` (静态链接, 无 cgo)

## 部署 (麒麟 V10)

```bash
# 把整个项目 rsync 到目标机 (含 bin/data 目录)
rsync -avz --exclude='.git' --exclude='scripts/' ./ root@kylin:/tmp/geocoder-deploy/

# 在目标机执行
ssh root@kylin "cd /tmp/geocoder-deploy && sudo ./deploy/install.sh"
```

install.sh 自动:
- 建用户 `geocoder` (nologin)
- 部署二进制到 `/opt/geocoder/bin/geocoder`
- 若 `data/geocoder.db` 存在, 拷到 `/var/lib/geocoder/geocoder.db`
- 注册 systemd 服务, 监听 `0.0.0.0:8000`
- 启用开机自启

## 验证

```bash
curl http://kylin:8000/health
curl 'http://kylin:8000/geocode?q=马六甲&limit=3'
```

## 日常运维

```bash
systemctl status geocoder          # 状态
systemctl restart geocoder         # 重启
journalctl -u geocoder -f          # 日志
```

## 卸载

```bash
sudo ./deploy/uninstall.sh         # 保留 db
sudo ./deploy/uninstall.sh --purge # 删 db
```

## 更新

```bash
# 1. Windows 重编
./deploy/build.sh
# 2. 拷到目标机 + 重启服务
scp bin/geocoder-linux-arm64 root@kylin:/tmp/
ssh root@kylin "cp /tmp/geocoder-linux-arm64 /opt/geocoder/bin/geocoder && systemctl restart geocoder"
```

## 防火墙 (麒麟 V10 默认 firewalld)

```bash
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload
```

## 端口/路径配置

install.sh 用默认 `0.0.0.0:8000` + `/var/lib/geocoder/geocoder.db`.
改默认: 编辑 install.sh 第 9-13 行的 `APP_DIR/DATA_DIR/SERVICE_NAME` 或 service 单元 `ExecStart` 行.
