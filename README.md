# GeoNames 数据使用指南

> 数据来源：https://www.geonames.org/ （CC-BY 4.0，署名 "GeoNames" 即可使用）
> 下载日期：2026-09-03

## 1. 网站是什么

开源地理地名数据库 (gazetteer)，覆盖全球所有国家，约 **1180 万条地名记录**。核心特点：

- 免费整包下载 + 免费 web API（有配额）+ 付费 premium 服务
- 地名词表型数据：只有**点坐标 + 属性**，无边界多边形、无道路网络
- 与 OSM（全要素矢量）/GADM（行政区边界）互补

每条记录字段：地名 ID、名称（多语言别名见 alternateNames）、经纬度、要素类别 (feature_class)、国家码 (ISO-3166 alpha-2)、四级行政区码、人口、高程、时区。

feature_class 关键值：`P`=居民点 `A`=行政区 `S`=设施 `T`=地形 `H`=水体 `L`=区域/公园

## 2. 数据量（实测）

| 文件 | 压缩大小 | 解压行数 | 内容 |
|---|---|---|---|
| allCountries.zip | 401.5M | 13,463,997 行 (~1.9GB) | 全量地名 |
| alternateNamesV2.zip | 194.4M | 19,148,540 行 | 多语言别名，按 geonameid join |
| cities1000.zip | 10.3M | — | 人口≥1000 的城市（轻量替代） |
| hierarchy.zip | 2.0M | — | parentId/childId 行政层级树 |
| countryInfo.txt | 30.9K | — | 国家元数据（首都、货币、语言等） |

按国家分文件在几百 KB–20MB 间，可只下需要的（如 `CN.zip`）。

## 3. 快速使用

### 3.1 现成脚本

`scripts/quickstart_geonames.py`（流式读 zip，峰值内存 <100MB，全扫约 1 分钟）：

```bash
python scripts/quickstart_geonames.py demo                     # 中国人口 Top10 城市
python scripts/quickstart_geonames.py nearby 39.9 116.4 100    # 北京 100km 内聚居点
python scripts/quickstart_geonames.py export CN out.csv        # 抽中国子集为 CSV
```

### 3.2 单次分析（duckdb，免导入）

```python
import duckdb
duckdb.sql("""SELECT name, latitude, longitude, population
  FROM 'data/allCountries.zip'
  WHERE country_code='JP' AND feature_class='P'
  ORDER BY population DESC LIMIT 10""").show()
```

### 3.3 高频查询 → PostgreSQL/PostGIS

```sql
CREATE TABLE geonames (geonameid int PRIMARY KEY, name text, lat float, lng float,
  fclass char(1), fcode text, country char(2), admin1 text, population bigint);
-- \copy 导入后:
CREATE INDEX ON geonames (country, fclass);
CREATE INDEX ON geonames USING gist (ll_to_earth(lat, lng));  -- 最近邻毫秒级
```

### 3.4 模糊地名搜索 → Elasticsearch/OpenSearch

bulk 导入，`name` + `alternatenames` 建 ngram 分词，"beijing"/"北京"/"Pekin" 均命中。

## 4. 典型场景

| 场景 | 用法 |
|---|---|
| 反向地理编码（坐标→城市） | cities1000 + haversine/PostGIS earthdistance |
| 地址标准化/地名消歧 | alternateNames 多语言别名匹配 |
| 省→市→县层级树 | hierarchy.zip 构建 |
| 时区查询 | timezone 字段直接读 |
| NLP 地名实体识别 | 词典匹配或 ES 索引 |

## 5. 注意事项

- **中国区域数据较粗糙**：省界以下覆盖不全，行政区标注按中国规范使用前需清洗；敏感区（台湾、藏南等标注）自行修正
- **中文别名覆盖不如英文**，对中文搜索需求建议补本地数据源
- 数据更新：dump 每日重建，可关注 modification_date 字段做增量
- 许可：CC-BY 4.0，产品/论文中署名 "GeoNames, geonames.org" 即可
- 与 F:/HIAN 的 OSM 数据互补：GeoNames 管"叫什么在哪"，OSM 管"长什么样、怎么连通"
