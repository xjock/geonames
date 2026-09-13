// /geocode 处理器: 主查 poi_master, fallback 天地图 + 回灌
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type POI struct {
	Source    string  `json:"source"`
	ID        any     `json:"id"`
	Name      string  `json:"name"`
	NameZh    string  `json:"name_zh,omitempty"`
	NameEn    string  `json:"name_en,omitempty"`
	Lat       float64 `json:"lat"`
	Lon       float64 `json:"lon"`
	CC        string  `json:"cc,omitempty"`
	Admin1    string  `json:"admin1,omitempty"`
	Placetype string  `json:"placetype,omitempty"`
	FCode     string  `json:"fcode,omitempty"`
	Pop       int64   `json:"pop,omitempty"`
	Score     float64 `json:"score"`
}

func (h *handlers) geocode(w http.ResponseWriter, r *http.Request) {
	t0 := time.Now()
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	if q == "" {
		http.Error(w, `{"error":"missing q"}`, 400)
		return
	}
	limit := 10
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 1 && n <= 50 {
			limit = n
		}
	}
	ccFilter := strings.ToUpper(r.URL.Query().Get("cc"))
	lang := strings.ToLower(r.URL.Query().Get("lang"))

	results := h.searchLocal(r.Context(), q, ccFilter, lang, limit*3)

	if len(results) == 0 && hasCJK(q) {
		tdtResults, err := h.tdtSearch(r.Context(), q, limit)
		if err == nil && len(tdtResults) > 0 {
			h.tdtCacheBack(r.Context(), q, tdtResults)
			results = tdtResults
		} else if err != nil {
			log.Printf("tdt error: %v", err)
		}
	}

	seen := map[string]bool{}
	out := make([]POI, 0, limit)
	for _, p := range results {
		key := fmt.Sprintf("%s|%.4f|%.4f", p.Name, p.Lat, p.Lon)
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, p)
		if len(out) >= limit {
			break
		}
	}

	resp := map[string]any{
		"q":          q,
		"elapsed_ms": int(time.Since(t0).Milliseconds()),
		"count":      len(out),
		"results":    out,
	}
	writeJSON(w, resp)
}

const poiSelectCols = `id, source, source_id,
	COALESCE(name_zh,''), COALESCE(name_en,''), lat, lon, COALESCE(cc,''),
	COALESCE(admin1,''), COALESCE(placetype,''), COALESCE(fcode,''),
	COALESCE(pop,0), COALESCE(importance,0)`

const pmSelectCols = `pm.id, pm.source, pm.source_id,
	COALESCE(pm.name_zh,''), COALESCE(pm.name_en,''), pm.lat, pm.lon, COALESCE(pm.cc,''),
	COALESCE(pm.admin1,''), COALESCE(pm.placetype,''), COALESCE(pm.fcode,''),
	COALESCE(pm.pop,0), COALESCE(pm.importance,0)`

func (h *handlers) searchLocal(ctx context.Context, q, ccFilter, lang string, limit int) []POI {
	out := []POI{}
	like := "%" + q + "%"
	qLower := strings.ToLower(q)

	ts := time.Now()
	rows, err := h.db.QueryContext(ctx, `
		SELECT `+poiSelectCols+`
		FROM poi_master
		WHERE (name_zh = ? COLLATE NOCASE OR name_en = ? COLLATE NOCASE)
		  AND lat IS NOT NULL AND lon IS NOT NULL
		  AND (? = '' OR cc = ?)
		ORDER BY importance DESC, pop DESC
		LIMIT ?`,
		q, q, ccFilter, ccFilter, limit)
	q1q := time.Since(ts).Milliseconds()
	q1s := int64(0)
	if err == nil {
		ts2 := time.Now()
		for rows.Next() {
			var p POI
			var sid, nzh, nen string
			if err := rows.Scan(&p.ID, &p.Source, &sid, &nzh, &nen, &p.Lat, &p.Lon, &p.CC,
				&p.Admin1, &p.Placetype, &p.FCode, &p.Pop, &p.Score); err != nil {
				continue
			}
			p.Name = pickName(nzh, nen, lang)
			p.Score = 1.0
			out = append(out, p)
		}
		rows.Close()
		q1s = time.Since(ts2).Milliseconds()
	}

	if len(out) < limit {
		ts = time.Now()
		rows2, err := h.db.QueryContext(ctx, `
			SELECT `+pmSelectCols+`
			FROM poi_name pn
			JOIN poi_master pm ON pm.id = pn.poi_id
			WHERE pn.name = ? COLLATE NOCASE
			  AND pm.lat IS NOT NULL AND pm.lon IS NOT NULL
			  AND (? = '' OR pm.cc = ?)
			ORDER BY pm.importance DESC, pm.pop DESC
			LIMIT ?`,
			q, ccFilter, ccFilter, limit)
		q2q := time.Since(ts).Milliseconds()
		q2s := int64(0)
		if err == nil {
			ts2 := time.Now()
			for rows2.Next() {
				var p POI
				var sid, nzh, nen string
				if err := rows2.Scan(&p.ID, &p.Source, &sid, &nzh, &nen, &p.Lat, &p.Lon, &p.CC,
					&p.Admin1, &p.Placetype, &p.FCode, &p.Pop, &p.Score); err != nil {
					continue
				}
				p.Name = pickName(nzh, nen, lang)
				p.Score = 0.95
				out = append(out, p)
			}
			rows2.Close()
			q2s = time.Since(ts2).Milliseconds()
		}
		log.Printf("[geocode] q=%q Q1q=%dms Q1s=%dms Q2q=%dms Q2s=%dms out=%d", q, q1q, q1s, q2q, q2s, len(out))
	}

	if len(out) < limit {
		ccClause := ""
		ccArgs := []any{}
		if ccFilter != "" {
			ccClause = "AND cc = ?"
			ccArgs = []any{ccFilter}
		}
		ts = time.Now()
		rows3, err := h.db.QueryContext(ctx,
			"SELECT "+poiSelectCols+" FROM poi_master WHERE (name_zh LIKE ? COLLATE NOCASE OR name_en LIKE ? COLLATE NOCASE) AND lat IS NOT NULL AND lon IS NOT NULL "+ccClause+" ORDER BY CASE WHEN lower(name_zh) = ? OR lower(name_en) = ? THEN 0 ELSE 1 END, importance DESC, pop DESC LIMIT ?",
			append(append([]any{like, like, qLower, qLower}, ccArgs...), limit)...)
		q3q := time.Since(ts).Milliseconds()
		q3s := int64(0)
		if err == nil {
			ts2 := time.Now()
			for rows3.Next() {
				var p POI
				var sid, nzh, nen string
				if err := rows3.Scan(&p.ID, &p.Source, &sid, &nzh, &nen, &p.Lat, &p.Lon, &p.CC,
					&p.Admin1, &p.Placetype, &p.FCode, &p.Pop, &p.Score); err != nil {
					continue
				}
				p.Name = pickName(nzh, nen, lang)
				if strings.EqualFold(p.Name, q) {
					p.Score = 1.0
				} else {
					p.Score = 0.85
				}
				out = append(out, p)
			}
			rows3.Close()
			q3s = time.Since(ts2).Milliseconds()
		}
		log.Printf("[geocode] q=%q Q3q=%dms Q3s=%dms out=%d", q, q3q, q3s, len(out))
	}
	return out
}

func hasCJK(s string) bool {
	for _, r := range s {
		if r >= 0x4E00 && r <= 0x9FFF {
			return true
		}
	}
	return false
}
