// geocoder: 中文地址编码 / 逆地理编码 API 服务
// - 纯 Go, 无 cgo (modernc.org/sqlite)
// - 数据: poi_master / poi_name / poi_bbox_index (由 Python 灌库脚本生成)
// - /geocode: 主查 poi_master + fallback 天地图 + 回灌
// - /reverse: poi_bbox_index + haversine 最近
// - /health: 行数统计
package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
)

func main() {
	addr := flag.String("addr", ":8000", "listen address")
	dbPath := flag.String("db", "data/geocoder.db", "sqlite path (relative to module root)")
	flag.Parse()

	db, err := openDB(*dbPath)
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer db.Close()
	log.Printf("[geocoder] db opened: %s", *dbPath)

	h := &handlers{db: db}

	// warmup: prime modernc/sqlite first-query init (~5-8s) before serving
	for _, t := range []string{"poi_master", "poi_name"} {
		var n int64
		if err := db.QueryRow("SELECT COUNT(*) FROM " + t).Scan(&n); err != nil {
			log.Fatalf("warmup %s: %v", t, err)
		}
		log.Printf("[geocoder] warmup %s=%d", t, n)
	}

	r := chi.NewRouter()

	// CORS — 测试界面跨域用
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Access-Control-Allow-Origin", "*")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusNoContent)
				return
			}
			next.ServeHTTP(w, r)
		})
	})

	r.Get("/health", h.health)
	r.Get("/geocode", h.geocode)
	r.Get("/reverse", h.reverse)

	// admin: 增量增删 + 索引重建
	r.Post("/admin/poi", h.adminUpsertPOI)
	r.Delete("/admin/poi", h.adminDeletePOI)
	r.Post("/admin/reindex", h.adminReindex)
	r.Get("/admin/reindex", h.adminReindexStatus)

	srv := &http.Server{
		Addr:              *addr,
		Handler:           r,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Printf("[geocoder] listening on %s", *addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("listen: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	<-stop
	log.Printf("[geocoder] shutting down")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Printf("shutdown: %v", err)
	}
}
