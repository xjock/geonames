# 麒麟 V10 (aarch64) 部署

默认安装位置: `/tools/sdb/data/world/names/` (二进制与 db 共目录).

## 一次性构建 (Windows host)

```bash
./deploy/build.sh
```

输出: `bin/geocoder-linux-arm64` (静态链接, 无 cgo, 9.9MB)

## 部署 (麒麟 V10)

```bash
# 把整个项目 rsync 到目标机
rsync -avz --exclude='.git' --exclude='scripts/' ./ root@kylin:/tmp/geocoder-deploy/

# 在目标机执行
ssh root@kylin "cd /tmp/geocoder-deploy && sudo ./deploy/install.sh"
```

install.sh 自动:
- 建用户 `geocoder` (nologin)
- 拷二进制到 `/tools/sdb/data/world/names/geocoder`
- 拷 db 到 `/tools/sdb/data/world/names/geocoder.db` (若不存在)
- 自动 chmod 父目录链 (geocoder 用户需 traverse)
- 注册 systemd 服务, 默认监听 `0.0.0.0:8000`
- 启用开机自启

## 端口冲突

8000 端口若被占用 (如 docker-proxy), 改 `install.sh` 顶部的 `LISTEN_ADDR`:
```bash
LISTEN_ADDR="0.0.0.0:8001"
```

## 验证

```bash
curl http://kylin:8000/health
curl 'http://kylin:8000/geocode?q=马六甲&limit=3'
curl 'http://kylin:8000/geocode?q=仰光&limit=5'   # 短查询走 RANGE 索引
curl 'http://kylin:8000/geocode?q=曼德勒&limit=5' # 3+ 字符走 FTS5
```

性能基准 (4.7M POI, ARM64):
- 短查询 (1-2 字符): 1-50ms
- 中等查询 (3+ 字符): 1-5ms (FTS5 命中)
- 平均 2-4ms

## 日常运维

```bash
systemctl status geocoder          # 状态
systemctl restart geocoder         # 重启
journalctl -u geocoder -f          # 日志
```

## 卸载

```bash
sudo ./deploy/uninstall.sh         # 保留 db
sudo ./deploy/uninstall.sh --purge # 删 db + 二进制
```

只删二进制, 不动 db.

## 更新

```bash
# 1. Windows 重编
./deploy/build.sh

# 2. 拷新二进制到目标机 + 重启
scp bin/geocoder-linux-arm64 root@kylin:/tools/sdb/data/world/names/geocoder
ssh root@kylin "systemctl restart geocoder"
```

无需重装服务. 只换 binary + 重启.

## 防火墙 (麒麟 V10 默认 firewalld)

```bash
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload
```

## 关键路径

| 用途 | 路径 |
|---|---|
| 二进制 | `/tools/sdb/data/world/names/geocoder` |
| 数据库 | `/tools/sdb/data/world/names/geocoder.db` |
| systemd 单元 | `/etc/systemd/system/geocoder.service` |
| 用户 | `geocoder` (无登录 shell) |

## 已知问题

- **父目录 traverse 权限**: `/tools/sdb/data/world` 默认 mode 700, install.sh 自动 `chmod o+rx` 父链. 若不想全局改权限, 把 geocoder 用户加入 root 组并 chmod g+rx.
- **8000 端口占用**: docker-proxy / 其它服务可能占 8000. 改 LISTEN_ADDR.
