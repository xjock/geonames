// SQLite 连接池 + WAL 配置 (modernc.org/sqlite, 纯 Go, CGO_ENABLED=0,
// 支持 linux/arm64 等交叉编译)
package main

import (
	"database/sql"
	"fmt"
	"path/filepath"
	"strings"
	"sync"

	_ "modernc.org/sqlite"
)

type DB struct {
	*sql.DB
	path string
}

type handlers struct {
	db   *DB
	once sync.Once
}

func openDB(path string) (*DB, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("abs: %w", err)
	}
	dsn := fmt.Sprintf("file:%s?_busy_timeout=5000&_synchronous=NORMAL&_journal_mode=WAL",
		filepath.ToSlash(abs))
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open: %w", err)
	}
	db.SetMaxOpenConns(8)
	db.SetMaxIdleConns(8)
	db.SetConnMaxIdleTime(0)
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("ping: %w", err)
	}
	return &DB{DB: db, path: abs}, nil
}

func pickName(nzh, nen, lang string) string {
	if strings.EqualFold(lang, "en") {
		if nen != "" {
			return nen
		}
		return nzh
	}
	if nzh != "" {
		return nzh
	}
	return nen
}
