# Geocoder API

Go 服务: `modernc.org/sqlite` (无 cgo) + 13.37 GB SQLite, ARM64 部署于麒麟 V10.
Base URL (生产): `http://xdbz:30080/geonames/`
本地直连: `http://127.0.0.1:8001/`

所有响应 `application/json; charset=utf-8`. 跨域已放行 (`Access-Control-Allow-Origin: *`).

---

## 1. GET /health

行数统计 + 数据源分布.

**响应**:
```json
{
  "poi_master": 4734423,
  "poi_name": 3711040,
  "poi_bbox_index": 0,
  "src_geonames": 3030692,
  "src_wof": 800000,
  "src_osm": 903730,
  "src_tdt": 1,
  "src_manual": 0
}
```

启动首查询 cold start ~1s (modernc JIT).

---

## 2. GET /geocode

正向编码: 关键字 → POI 列表.

### Query 参数

| 参数 | 必填 | 默认 | 范围 | 说明 |
|---|---|---|---|---|
| `q` | ✅ | — | 1-50 字符 | 查询关键字 (中文/英文/拼音) |
| `limit` | ❌ | 10 | 1-50 | 返回条数 |
| `cc` | ❌ | `""` | ISO 3166-1 alpha-2 (MM/TH/VN/...) | 国家过滤 |
| `lang` | ❌ | `""` | `zh` / `en` | 名称语言偏好 |

### 检索策略 (三段执行, 去重合并)

1. **Q1 精确命中**: `poi_master.name_zh = ? OR name_en = ?` (idx_pm_name_zh/en), score=1.0
2. **Q2 别名命中**: `poi_name.name = ?` JOIN `poi_master` (idx_pn_name), score=0.95
3. **Q3 模糊**:
   - **3+ 字符** → FTS5 trigram `poi_fts MATCH "..."`, score=0.85 (1.0 当 equalfold)
   - **1-2 字符** → B-tree 范围扫描 `name_zh >= q AND name_zh < q || 0xFFFF`, score=0.85

CJK 查询无本地结果时, 自动 fallback 天地图 v2 搜索 + 回灌 `poi_master` (source='tdt').

### 响应

```json
{
  "q": "马六甲",
  "elapsed_ms": 2,
  "count": 2,
  "results": [
    {
      "source": "geonames",
      "id": 1702670,
      "name": "马六甲",
      "name_zh": "马六甲",
      "name_en": "Malacca",
      "lat": 2.196,
      "lon": 102.2505,
      "cc": "MY",
      "admin1": "Melaka",
      "placetype": "locality",
      "fcode": "PPLC",
      "pop": 180400,
      "score": 1.0
    }
  ]
}
```

字段省略规则: 空值 (`""` 或 0) 的字段被 omitempty.

### 示例

```
GET /geocode?q=马六甲&limit=3
GET /geocode?q=曼德勒&limit=5
GET /geocode?q=仰光&cc=MM
GET /geocode?q=Mandalay&lang=en
```

### 性能

| 查询长度 | 路径 | 延迟 |
|---|---|---|
| 1-2 字符 | RANGE 索引 | 1-50ms |
| 3+ 字符 | FTS5 | 1-5ms |
| 平均 | — | 2-4ms |

---

## 3. GET /reverse

逆地理编码: 经纬度 → 最近 POI + 行政链.

### Query 参数

| 参数 | 必填 | 默认 | 范围 | 说明 |
|---|---|---|---|---|
| `lon` | ✅ | — | -180 ~ 180 | 经度 |
| `lat` | ✅ | — | -90 ~ 90 | 纬度 |
| `radius_m` | ❌ | 5000 | 100-50000 | 搜索半径 (米) |
| `lang` | ❌ | `""` | `zh` / `en` | 名称语言 |

### 算法

1. **行政链**: `poi_bbox_index` 矩形相交 + placetype 优先级 (country→region→county→localadmin→locality→borough→neighbourhood), 最多 6 层
2. **最近 POI**: `poi_master` lat/lon 范围筛选 + 平方距离 ORDER BY + haversine 精算, 仅当距离 ≤ radius 时返回

### 响应

```json
{
  "lon": 96.156,
  "lat": 16.840,
  "admin": [
    {"id": 1327865, "name": "缅甸", "cc": "MM", "placetype": "country", "dist_m": 0},
    {"id": 1311870, "name": "仰光", "cc": "MM", "placetype": "region", "dist_m": 0}
  ],
  "nearest": {
    "id": 1702670,
    "name": "仰光",
    "lat": 16.8409,
    "lon": 96.1735,
    "cc": "MM",
    "admin1": "Yangon",
    "placetype": "locality",
    "fcode": "PPLC",
    "pop": 4477638,
    "dist_m": 1893
  },
  "elapsed_ms": 3
}
```

`admin` 为空 / `nearest` 缺失表示无数据. `poi_bbox_index` 当前为 0 行 (未启用), 仅 `nearest` 生效.

### 示例

```
GET /reverse?lat=22.567358&lon=95.694763&radius_m=10000
GET /reverse?lat=16.84&lon=96.16&lang=en
```

---

## 4. POST /admin/poi

POI 增量 upsert. 鉴权: 设置 `ADMIN_TOKEN` 环境变量后, 请求头需带 `X-Admin-Token`.

### 请求体 (单条)

```json
{
  "source": "manual",
  "source_id": "my-001",
  "region": "sea",
  "cc": "MM",
  "name_zh": "皎漂",
  "name_en": "Kyaukpyu",
  "name_local": "ကျောက်ဖြူ",
  "lat": 19.4235,
  "lon": 93.5490,
  "placetype": "locality",
  "fcode": "PPL",
  "admin1": "Rakhine",
  "pop": 20000,
  "importance": 0.4,
  "names": [
    {"lang": "my", "name": "ကျောက်ဖြူ"},
    {"lang": "en", "name": "Kyaukpyu"}
  ]
}
```

也支持数组 `[ {...}, {...} ]`, 上限 10000 条/请求.

### 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source` | string | ✅ | enum: `osm`/`tdt`/`geonames`/`wof`/`manual` |
| `source_id` | string | ✅ | 原始 id, 与 source 组成幂等键 |
| `region` | string | ❌ | `sea`/`afr`/`me`/`cn`/`global`, 默认 `global` |
| `cc` | string | ❌ | ISO 3166-1 alpha-2 |
| `name_zh`/`name_en`/`name_local` | string | 至少一个 | — |
| `altnames` | string | ❌ | JSON dict, 可选 |
| `lat`/`lon` | float | ✅ | — |
| `bbox_min_lat/lon/max_lat/max_lon` | float | ❌ | 仅面状 |
| `placetype`/`fclass`/`fcode` | string | ❌ | GeoNames 标准 |
| `admin1..4` | string | ❌ | 行政层级 |
| `pop` | int | ❌ | — |
| `importance` | float | ❌ | 0-1 |
| `names[]` | array | ❌ | 附加多语言, 写 `poi_name` 表 |

### 响应

```json
{"ok": 1, "skipped": 0}
```

---

## 5. DELETE /admin/poi

### Query 参数 (三选一)

| 模式 | 参数 |
|---|---|
| 按 id | `?id=12345` |
| 按 source + source_id | `?source=osm&source_id=n12345` |
| 清空整源 | `?source=tdt&confirm=yes` ⚠️ 危险 |

### 响应

```json
{"deleted": 1}
```

---

## 6. POST /admin/reindex

异步重建查询索引. 后台 goroutine 执行, 不阻塞响应.

### 重建步骤

1. DROP/CREATE `idx_pm_name_zh_nc` (NOCASE)
2. DROP/CREATE `idx_pm_name_en_nc` (NOCASE)
3. DROP/CREATE `idx_pn_name` (NOCASE)
4. DROP/CREATE `idx_pm_lat_lon`
5. `PRAGMA wal_checkpoint(TRUNCATE)`

### 响应

```json
{"status": "started"}
```

若正在运行:
```json
{"status": "already_running", "started": "2026-09-14T17:30:00Z"}
```

---

## 7. GET /admin/reindex

查询重建状态.

### 响应

```json
{
  "running": false,
  "started": "2026-09-14T17:30:00Z",
  "finished": "2026-09-14T17:35:42Z",
  "err": "",
  "log": [
    "drop idx_pm_name_zh_nc: ok (0.1s)",
    "create idx_pm_name_zh_nc: ok (24.3s)",
    "drop idx_pm_name_en_nc: ok (0.1s)",
    "create idx_pm_name_en_nc: ok (18.7s)",
    "drop idx_pn_name: ok (0.1s)",
    "create idx_pn_name: ok (9.2s)",
    "drop idx_pm_lat_lon: ok (0.1s)",
    "create idx_pm_lat_lon: ok (6.5s)",
    "wal_checkpoint: ok (0.4s)"
  ]
}
```

---

## 错误码

| 状态码 | 触发 |
|---|---|
| 400 | `q` 缺失 / 反序列化失败 / DELETE 参数不全 / POI 字段全空 |
| 401 | 启用 `ADMIN_TOKEN` 但缺/错 `X-Admin-Token` |
| 500 | SQLite 异常 |

错误响应体一律 `{"error": "..."}`.

---

## 数据源 (`source` 字段)

| 值 | 说明 |
|---|---|
| `geonames` | GeoNames 数据集导入 (主力, 3.03M) |
| `osm` | OpenStreetMap (0.9M, 后续阶段) |
| `wof` | Who's On First 行政层级 (0.8M) |
| `tdt` | 天地图 v2 在线回灌 |
| `manual` | `POST /admin/poi` 手动写入 |

---

## CORS

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

OPTIONS 预检直接 204.

---

## 性能基准 (生产 xdbz, 4.7M POI)

| 接口 | P50 | P99 |
|---|---|---|
| `/health` | 1ms (warm) / 1.1s (cold) | 1.2s |
| `/geocode` (1-2 字符) | 5ms | 50ms |
| `/geocode` (3+ 字符, FTS5) | 2ms | 5ms |
| `/reverse` | 3ms | 15ms |
| `/admin/poi` (单条) | 2ms | 10ms |
| `/admin/poi` (1000 条批量) | 350ms | 800ms |

SQLite WAL 模式, 单连接串行写 + 读并发. `/admin/reindex` 全量重建 ~1min (依赖 db 大小).
