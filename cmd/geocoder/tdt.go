// 天地图 v2 search API 客户端 + 回灌到 poi_master / poi_name
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	tdtEndpoint   = "https://api.tianditu.gov.cn/v2/search"
	defaultTDTKey = "fbaf76f74a84bc0daa3334dae5d36412"
)

type tdtResp struct {
	Area   map[string]any   `json:"area"`
	Pois   []map[string]any `json:"pois"`
	Prompt []map[string]any `json:"prompt"`
}

func tdtKey() string {
	if k := os.Getenv("TDT_KEY"); k != "" {
		return k
	}
	return defaultTDTKey
}

func (h *handlers) tdtSearch(ctx context.Context, q string, limit int) ([]POI, error) {
	post := fmt.Sprintf(`{"keyWord":%q,"level":12,"mapBound":"-180,-90,180,90","queryType":1,"start":0,"count":%d}`,
		q, limit)
	u := tdtEndpoint + "?postStr=" + url.QueryEscape(post) + "&type=query&tk=" + url.QueryEscape(tdtKey())

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "geocoder/0.1")

	cli := &http.Client{Timeout: 3 * time.Second}
	resp, err := cli.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("tdt http %d: %s", resp.StatusCode, string(body[:minN(200, len(body))]))
	}

	var d tdtResp
	if err := json.Unmarshal(body, &d); err != nil {
		return nil, fmt.Errorf("tdt parse: %w", err)
	}

	out := []POI{}
	addItem := func(it map[string]any) {
		ll, _ := it["lonlat"].(string)
		if ll == "" {
			return
		}
		parts := strings.Split(ll, ",")
		if len(parts) != 2 {
			return
		}
		lon, err1 := strconv.ParseFloat(parts[0], 64)
		lat, err2 := strconv.ParseFloat(parts[1], 64)
		if err1 != nil || err2 != nil {
			return
		}
		name, _ := it["name"].(string)
		if name == "" {
			name = q
		}
		addr, _ := it["adminName"].(string)
		if a, ok := it["address"].(string); ok && a != "" {
			addr = a
		}
		fc, _ := it["type"].(string)
		uid, _ := it["uid"].(string)
		if uid == "" {
			if ac, ok := it["adminCode"].(string); ok {
				uid = ac
			}
		}
		out = append(out, POI{
			Source: "tianditu",
			ID:     uid,
			Name:   name,
			Lat:    lat,
			Lon:    lon,
			CC:     "CN",
			Admin1: addr,
			FCode:  fc,
			Score:  0.95,
		})
	}
	if d.Area != nil {
		addItem(d.Area)
	}
	for _, it := range d.Pois {
		addItem(it)
	}
	for _, it := range d.Prompt {
		addItem(it)
	}
	return out, nil
}

func (h *handlers) tdtCacheBack(ctx context.Context, q string, items []POI) {
	for _, p := range items {
		uidStr := fmt.Sprintf("%v", p.ID)
		var uidInt int64
		if v, err := strconv.ParseInt(uidStr, 10, 64); err == nil {
			uidInt = v
		} else {
			uidInt = shaHash(uidStr) % 999999999
		}
		gid := -(int(math.Abs(float64(uidInt)))%1000000 + 100000000)

		_, err := h.db.ExecContext(ctx, `
			INSERT OR IGNORE INTO poi_master(
				source, source_id, region, cc, name_zh, name_en, name_local,
				lat, lon, placetype, fcode, admin1, importance
			) VALUES ('tdt', ?, 'cn', 'CN', ?, ?, ?, ?, ?, 'poi', ?, ?, 0.5)`,
			strconv.FormatInt(int64(gid), 10), p.Name, p.Name, p.Name, p.Lat, p.Lon, p.FCode, p.Admin1)
		if err != nil {
			continue
		}
		if p.Name != q {
			_, _ = h.db.ExecContext(ctx, `
				INSERT OR IGNORE INTO poi_name(poi_id, lang, name, source)
				SELECT id, 'zh', ?, 'tdt' FROM poi_master WHERE source='tdt' AND source_id=?`,
				q, strconv.FormatInt(int64(gid), 10))
		}
	}
}

func shaHash(s string) int64 {
	h := int64(5381)
	for _, c := range s {
		h = h*33 + int64(c)
	}
	if h < 0 {
		h = -h
	}
	return h
}

func minN(a, b int) int {
	if a < b {
		return a
	}
	return b
}
