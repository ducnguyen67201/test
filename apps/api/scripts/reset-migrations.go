package main

import (
	"context"
	"fmt"
	"log"

	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	ctx := context.Background()

	// Database connection
	connStr := "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable"

	pool, err := pgxpool.New(ctx, connStr)
	if err != nil {
		log.Fatal("Failed to connect to database:", err)
	}
	defer pool.Close()

	// Test connection
	if err := pool.Ping(ctx); err != nil {
		log.Fatal("Failed to ping database:", err)
	}

	fmt.Println("✓ Connected to database")

	// Drop schema_migrations table
	fmt.Println("\nDropping schema_migrations table...")
	_, err = pool.Exec(ctx, "DROP TABLE IF EXISTS schema_migrations CASCADE")
	if err != nil {
		log.Fatal("Failed to drop schema_migrations:", err)
	}
	fmt.Println("✓ schema_migrations table dropped")

	// Check current tables
	fmt.Println("\nCurrent tables in database:")
	rows, err := pool.Query(ctx, `
		SELECT tablename
		FROM pg_tables
		WHERE schemaname = 'public'
		ORDER BY tablename
	`)
	if err != nil {
		log.Fatal("Failed to query tables:", err)
	}
	defer rows.Close()

	hasTablesinDB := false
	for rows.Next() {
		var tableName string
		if err := rows.Scan(&tableName); err != nil {
			log.Fatal("Failed to scan row:", err)
		}
		fmt.Printf("  - %s\n", tableName)
		hasTablesinDB = true
	}

	if !hasTablesinDB {
		fmt.Println("  (no tables found)")
	}

	fmt.Println("\n✓ Migration state reset complete!")
	fmt.Println("\nNow run: .\\scripts\\migrate.ps1 up")
}
