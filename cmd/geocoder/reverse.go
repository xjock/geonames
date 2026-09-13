// /reverse 处理器: poi_bbox_index 命中 + poi_master haversine 最近
// /health 处理器: 行数统计
package main

import (
	"bytes"
	"encoding/json"
	"math"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"
)

func writeJSON(w http.ResponseWriter, v any) {
	var buf bytes.Buffer
	if err := json.NewEncoder(&buf).Encode(v); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Content-Length", strconv.Itoa(buf.Len()))
	w.Write(buf.Bytes())
}

func (h *handlers) reverse(w http.ResponseWriter, r *http.Request) {
	t0 := time.Now()
	q := r.URL.Query()
	lon, err1 := strconv.ParseFloat(q.Get("lon"), 64)
	lat, err2 := strconv.ParseFloat(q.Get("lat"), 64)
	if err1 != nil || err2 != nil {
		http.Error(w, `{"error":"invalid lon/lat"}`, 400)
		return
	}
	radius := 5000.0
	if v := q.Get("radius_m"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 100 && n <= 50000 {
			radius = float64(n)
		}
	}
	lang := strings.ToLower(q.Get("lang"))

	out := map[string]any{
		"lon": lon,
		"lat": lat,
	}

	adminRows, err := h.db.QueryContext(r.Context(), `
		SELECT pm.id, pm.source, COALESCE(pm.name_zh,''), COALESCE(pm.name_en,''),
		       COALESCE(pm.cc,''), COALESCE(pm.placetype,''), pm.lat, pm.lon
		FROM poi_bbox_index pb
		JOIN poi_master pm ON pm.id = pb.poi_id
		WHERE pb.min_lat <= ? AND pb.max_lat >= ?
		  AND pb.min_lon <= ? AND pb.max_lon >= ?
		LIMIT 50`,
		lat, lat, lon, lon)
	adminChain := []map[string]any{}
	if err == nil {
		prio := map[string]int{
			"country": 1, "region": 2, "county": 3, "localadmin": 4,
			"locality": 5, "borough": 6, "neighbourhood": 7,
		}
		for adminRows.Next() {
			var p POI
			var nzh, nen string
			if err := adminRows.Scan(&p.ID, &p.Source, &nzh, &nen, &p.CC,
				&p.Placetype, &p.Lat, &p.Lon); err != nil {
				continue
			}
			p.Name = pickName(nzh, nen, lang)
			d := haversine(lat, lon, p.Lat, p.Lon)
			adminChain = append(adminChain, map[string]any{
				"id":        p.ID,
				"name":      p.Name,
				"cc":        p.CC,
				"placetype": p.Placetype,
				"dist_m":    int(d),
			})
		}
		adminRows.Close()
		sort.Slice(adminChain, func(i, j int) bool {
			pi, _ := adminChain[i]["placetype"].(string)
			pj, _ := adminChain[j]["placetype"].(string)
			return prio[pi] < prio[pj]
		})
		if len(adminChain) > 6 {
			adminChain = adminChain[:6]
		}
	}
	out["admin"] = adminChain

	degp := radius / 111000.0
	row := h.db.QueryRowContext(r.Context(), `
		SELECT id, source, COALESCE(name_zh,''), COALESCE(name_en,''), lat, lon,
		       COALESCE(cc,''), COALESCE(admin1,''), COALESCE(placetype,''),
		       COALESCE(fcode,''), COALESCE(pop,0)
		FROM poi_master
		WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
		ORDER BY (lat-?)*(lat-?) + (lon-?)*(lon-?)
		LIMIT 1`,
		lat-degp, lat+degp, lon-degp, lon+degp,
		lat, lat, lon, lon)
	var p POI
	var nzh, nen, a1, pt, fc string
	var pop int64
	if err := row.Scan(&p.ID, &p.Source, &nzh, &nen, &p.Lat, &p.Lon, &p.CC,
		&a1, &pt, &fc, &pop); err == nil {
		p.Name = pickName(nzh, nen, lang)
		p.Admin1 = a1
		p.Placetype = pt
		p.FCode = fc
		p.Pop = pop
		d := haversine(lat, lon, p.Lat, p.Lon)
		if d <= radius {
			out["nearest"] = map[string]any{
				"id":        p.ID,
				"name":      p.Name,
				"lat":       p.Lat,
				"lon":       p.Lon,
				"cc":        p.CC,
				"admin1":    a1,
				"placetype": pt,
				"fcode":     fc,
				"pop":       pop,
				"dist_m":    int(d),
			}
		}
	}

	out["elapsed_ms"] = int(time.Since(t0).Milliseconds())
	writeJSON(w, out)
}

func (h *handlers) health(w http.ResponseWriter, r *http.Request) {
	stats := map[string]int64{}
	for _, t := range []string{"poi_master", "poi_name", "poi_bbox_index"} {
		var n int64
		if err := h.db.QueryRowContext(r.Context(), "SELECT COUNT(*) FROM "+t).Scan(&n); err == nil {
			stats[t] = n
		} else {
			stats[t] = -1
		}
	}
	for _, t := range []string{"geonames", "wof", "osm", "tdt", "manual"} {
		var n int64
		if err := h.db.QueryRowContext(r.Context(), "SELECT COUNT(*) FROM poi_master WHERE source=?", t).Scan(&n); err == nil {
			stats["src_"+t] = n
		}
	}
	writeJSON(w, stats)
}

func haversine(lat1, lon1, lat2, lon2 float64) float64 {
	const R = 6371000.0
	p1 := lat1 * math.Pi / 180
	p2 := lat2 * math.Pi / 180
	dp := (lat2 - lat1) * math.Pi / 180
	dl := (lon2 - lon1) * math.Pi / 180
	a := math.Sin(dp/2)*math.Sin(dp/2) + math.Cos(p1)*math.Cos(p2)*math.Sin(dl/2)*math.Sin(dl/2)
	return R * 2 * math.Atan2(math.Sqrt(a), math.Sqrt(1-a))
}
