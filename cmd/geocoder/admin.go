// /admin 接口: 增量 POI 增删 + 索引重建 (异步)
// - POST /admin/poi        单条/批量 upsert (body: POI 或 []POIInput)
// - DELETE /admin/poi      按 source+source_id 或 id 删除
// - POST /admin/reindex    重建索引 (后台执行)
// - GET  /admin/reindex    查询重建状态
// 鉴权: 若设置环境变量 ADMIN_TOKEN, 请求需带 X-Admin-Token 头
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

// POIInput 增量写入输入; source+source_id 为幂等键
type POIInput struct {
	Source    string  `json:"source"`
	SourceID  string  `json:"source_id"`
	Region    string  `json:"region"`
	CC        string  `json:"cc"`
	NameZh    string  `json:"name_zh"`
	NameEn    string  `json:"name_en"`
	NameLocal string  `json:"name_local"`
	AltNames  string  `json:"altnames"`
	Lat       float64 `json:"lat"`
	Lon       float64 `json:"lon"`
	BBoxMinLat *float64 `json:"bbox_min_lat"`
	BBoxMinLon *float64 `json:"bbox_min_lon"`
	BBoxMaxLat *float64 `json:"bbox_max_lat"`
	BBoxMaxLon *float64 `json:"bbox_max_lon"`
	Placetype string  `json:"placetype"`
	FClass    string  `json:"fclass"`
	FCode     string  `json:"fcode"`
	Admin1    string  `json:"admin1"`
	Admin2    string  `json:"admin2"`
	Admin3    string  `json:"admin3"`
	Admin4    string  `json:"admin4"`
	Pop       int64   `json:"pop"`
	Importance float64 `json:"importance"`
	// 额外多语言名 (可选): [{"lang":"zh","name":"曼德勒"}]
	Names []struct {
		Lang string `json:"lang"`
		Name string `json:"name"`
	} `json:"names"`
}

type reindexState struct {
	mu      sync.Mutex
	running bool
	started string
	finished string
	log     []string
	err     string
}

var reindexSt = &reindexState{}

func (h *handlers) adminAuth(w http.ResponseWriter, r *http.Request) bool {
	tok := os.Getenv("ADMIN_TOKEN")
	if tok == "" {
		return true
	}
	if r.Header.Get("X-Admin-Token") != tok {
		http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
		return false
	}
	return true
}

// POST /admin/poi — body 为单对象或数组
func (h *handlers) adminUpsertPOI(w http.ResponseWriter, r *http.Request) {
	if !h.adminAuth(w, r) {
		return
	}
	var items []POIInput
	dec := json.NewDecoder(r.Body)
	raw := json.RawMessage{}
	if err := dec.Decode(&raw); err != nil {
		http.Error(w, `{"error":"invalid json"}`, 400)
		return
	}
	raw = json.RawMessage(strings.TrimSpace(string(raw)))
	if len(raw) > 0 && raw[0] == '[' {
		if err := json.Unmarshal(raw, &items); err != nil {
			http.Error(w, `{"error":"invalid array"}`, 400)
			return
		}
	} else {
		var one POIInput
		if err := json.Unmarshal(raw, &one); err != nil {
			http.Error(w, `{"error":"invalid object"}`, 400)
			return
		}
		items = []POIInput{one}
	}
	if len(items) == 0 {
		http.Error(w, `{"error":"empty"}`, 400)
		return
	}
	if len(items) > 10000 {
		http.Error(w, `{"error":"max 10000 per call"}`, 400)
		return
	}

	ctx := r.Context()
	tx, err := h.db.BeginTx(ctx, nil)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
		return
	}
	defer tx.Rollback()

	stmt, err := tx.PrepareContext(ctx, `
		INSERT INTO poi_master(
			source, source_id, region, cc, name_zh, name_en, name_local,
			altnames, lat, lon,
			bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon,
			placetype, fclass, fcode, admin1, admin2, admin3, admin4,
			region_id, country_id, pop, importance
		) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)
		ON CONFLICT(source, source_id) DO UPDATE SET
			region=excluded.region, cc=excluded.cc,
			name_zh=excluded.name_zh, name_en=excluded.name_en,
			name_local=excluded.name_local, altnames=excluded.altnames,
			lat=excluded.lat, lon=excluded.lon,
			bbox_min_lat=excluded.bbox_min_lat, bbox_min_lon=excluded.bbox_min_lon,
			bbox_max_lat=excluded.bbox_max_lat, bbox_max_lon=excluded.bbox_max_lon,
			placetype=excluded.placetype, fclass=excluded.fclass, fcode=excluded.fcode,
			admin1=excluded.admin1, admin2=excluded.admin2,
			admin3=excluded.admin3, admin4=excluded.admin4,
			pop=excluded.pop, importance=excluded.importance`)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
		return
	}
	defer stmt.Close()

	idStmt, err := tx.PrepareContext(ctx,
		`SELECT id FROM poi_master WHERE source=? AND source_id=?`)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
		return
	}
	defer idStmt.Close()

	nameStmt, err := tx.PrepareContext(ctx,
		`INSERT OR IGNORE INTO poi_name(poi_id, lang, name, is_official, source) VALUES (?,?,?,0,?)`)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
		return
	}
	defer nameStmt.Close()

	ok, skipped := 0, 0
	for _, it := range items {
		if it.Source == "" || it.SourceID == "" || (it.NameZh == "" && it.NameEn == "" && it.NameLocal == "") {
			skipped++
			continue
		}
		region := it.Region
		if region == "" {
			region = "global"
		}
		_, err := stmt.ExecContext(ctx,
			it.Source, it.SourceID, region, it.CC, it.NameZh, it.NameEn, it.NameLocal,
			it.AltNames, it.Lat, it.Lon,
			it.BBoxMinLat, it.BBoxMinLon, it.BBoxMaxLat, it.BBoxMaxLon,
			it.Placetype, it.FClass, it.FCode, it.Admin1, it.Admin2, it.Admin3, it.Admin4,
			it.Pop, it.Importance)
		if err != nil {
			skipped++
			continue
		}
		// 写入附加名称
		if len(it.Names) > 0 {
			var pid int64
			if err := idStmt.QueryRowContext(ctx, it.Source, it.SourceID).Scan(&pid); err == nil {
				for _, nm := range it.Names {
					if nm.Lang != "" && nm.Name != "" {
						_, _ = nameStmt.ExecContext(ctx, pid, nm.Lang, nm.Name, it.Source)
					}
				}
			}
		}
		ok++
	}
	if err := tx.Commit(); err != nil {
		http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
		return
	}
	writeJSON(w, map[string]any{"ok": ok, "skipped": skipped})
}

// DELETE /admin/poi?source=X&source_id=Y 或 ?id=123
// 或 ?source=X (整源清空, 需 &confirm=yes)
func (h *handlers) adminDeletePOI(w http.ResponseWriter, r *http.Request) {
	if !h.adminAuth(w, r) {
		return
	}
	q := r.URL.Query()
	ctx := r.Context()

	tx, err := h.db.BeginTx(ctx, nil)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
		return
	}
	defer tx.Rollback()

	var n int64
	if id := q.Get("id"); id != "" {
		_, _ = tx.ExecContext(ctx, `DELETE FROM poi_name WHERE poi_id=?`, id)
		res, err := tx.ExecContext(ctx, `DELETE FROM poi_master WHERE id=?`, id)
		if err != nil {
			http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
			return
		}
		n, _ = res.RowsAffected()
	} else if src, sid := q.Get("source"), q.Get("source_id"); src != "" && sid != "" {
		_, _ = tx.ExecContext(ctx,
			`DELETE FROM poi_name WHERE poi_id IN (SELECT id FROM poi_master WHERE source=? AND source_id=?)`, src, sid)
		res, err := tx.ExecContext(ctx,
			`DELETE FROM poi_master WHERE source=? AND source_id=?`, src, sid)
		if err != nil {
			http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
			return
		}
		n, _ = res.RowsAffected()
	} else if src := q.Get("source"); src != "" && q.Get("confirm") == "yes" {
		_, _ = tx.ExecContext(ctx,
			`DELETE FROM poi_name WHERE poi_id IN (SELECT id FROM poi_master WHERE source=?)`, src)
		res, err := tx.ExecContext(ctx, `DELETE FROM poi_master WHERE source=?`, src)
		if err != nil {
			http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
			return
		}
		n, _ = res.RowsAffected()
	} else {
		http.Error(w, `{"error":"need id, or source+source_id, or source+confirm=yes"}`, 400)
		return
	}
	if err := tx.Commit(); err != nil {
		http.Error(w, fmt.Sprintf(`{"error":%q}`, err.Error()), 500)
		return
	}
	writeJSON(w, map[string]any{"deleted": n})
}

// POST /admin/reindex — 后台重建全部查询索引 + ANALYZE
func (h *handlers) adminReindex(w http.ResponseWriter, r *http.Request) {
	if !h.adminAuth(w, r) {
		return
	}
	reindexSt.mu.Lock()
	if reindexSt.running {
		reindexSt.mu.Unlock()
		writeJSON(w, map[string]any{"status": "already_running", "started": reindexSt.started})
		return
	}
	reindexSt.running = true
	reindexSt.started = time.Now().Format(time.RFC3339)
	reindexSt.finished = ""
	reindexSt.err = ""
	reindexSt.log = nil
	reindexSt.mu.Unlock()

	go h.runReindex()
	writeJSON(w, map[string]any{"status": "started"})
}

// GET /admin/reindex — 状态
func (h *handlers) adminReindexStatus(w http.ResponseWriter, r *http.Request) {
	if !h.adminAuth(w, r) {
		return
	}
	reindexSt.mu.Lock()
	defer reindexSt.mu.Unlock()
	writeJSON(w, map[string]any{
		"running":  reindexSt.running,
		"started":  reindexSt.started,
		"finished": reindexSt.finished,
		"err":      reindexSt.err,
		"log":      reindexSt.log,
	})
}

func (h *handlers) runReindex() {
	steps := []struct{ name, sql string }{
		{"drop idx_pm_name_zh_nc", `DROP INDEX IF EXISTS idx_pm_name_zh_nc`},
		{"create idx_pm_name_zh_nc", `CREATE INDEX idx_pm_name_zh_nc ON poi_master(name_zh COLLATE NOCASE)`},
		{"drop idx_pm_name_en_nc", `DROP INDEX IF EXISTS idx_pm_name_en_nc`},
		{"create idx_pm_name_en_nc", `CREATE INDEX idx_pm_name_en_nc ON poi_master(name_en COLLATE NOCASE)`},
		{"drop idx_pn_name", `DROP INDEX IF EXISTS idx_pn_name`},
		{"create idx_pn_name", `CREATE INDEX idx_pn_name ON poi_name(name COLLATE NOCASE)`},
		{"drop idx_pm_lat_lon", `DROP INDEX IF EXISTS idx_pm_lat_lon`},
		{"create idx_pm_lat_lon", `CREATE INDEX idx_pm_lat_lon ON poi_master(lat, lon)`},
		{"wal_checkpoint", `PRAGMA wal_checkpoint(TRUNCATE)`},
	}
	ctx := context.Background()
	for _, s := range steps {
		t0 := time.Now()
		_, err := h.db.ExecContext(ctx, s.sql)
		status := "ok"
		if err != nil {
			status = "ERR " + err.Error()
		}
		msg := fmt.Sprintf("%s: %s (%.1fs)", s.name, status, time.Since(t0).Seconds())
		reindexSt.mu.Lock()
		reindexSt.log = append(reindexSt.log, msg)
		if err != nil {
			reindexSt.err = err.Error()
		}
		reindexSt.mu.Unlock()
		if err != nil {
			break
		}
	}
	reindexSt.mu.Lock()
	reindexSt.running = false
	reindexSt.finished = time.Now().Format(time.RFC3339)
	reindexSt.mu.Unlock()
}
