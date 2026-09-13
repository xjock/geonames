// SQLite 连接池 + WAL 配置 (mattn/go-sqlite3, cgo)
package main

import (
	"database/sql"
	"fmt"
	"path/filepath"
	"strings"
	"sync"

	_ "github.com/mattn/go-sqlite3"
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
	dsn := fmt.Sprintf("file:%s?_busy_timeout=10000&_synchronous=NORMAL&_journal_mode=WAL",
		filepath.ToSlash(abs))
	db, err := sql.Open("sqlite3", dsn)
	if err != nil {
		return nil, fmt.Errorf("open: %w", err)
	}
	db.SetMaxOpenConns(16)
	db.SetMaxIdleConns(4)
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
