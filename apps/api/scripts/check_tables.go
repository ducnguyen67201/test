package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		dbURL = "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable"
	}

	pool, err := pgxpool.New(context.Background(), dbURL)
	if err != nil {
		log.Fatal("Failed to connect:", err)
	}
	defer pool.Close()

	// Query to list all tables
	query := `
		SELECT table_name
		FROM information_schema.tables
		WHERE table_schema = 'public'
		ORDER BY table_name;
	`

	rows, err := pool.Query(context.Background(), query)
	if err != nil {
		log.Fatal("Failed to query tables:", err)
	}
	defer rows.Close()

	fmt.Println("Tables in database 'zerozero':")
	fmt.Println("================================")

	count := 0
	for rows.Next() {
		var tableName string
		if err := rows.Scan(&tableName); err != nil {
			log.Fatal("Failed to scan:", err)
		}
		count++
		fmt.Printf("%d. %s\n", count, tableName)
	}

	if count == 0 {
		fmt.Println("No tables found!")
	} else {
		fmt.Printf("\nTotal tables: %d\n", count)
	}

	// Also check migration version from schema_migrations table
	fmt.Println("\n================================")
	fmt.Println("Migration history:")
	fmt.Println("================================")

	versionQuery := `SELECT version, dirty FROM schema_migrations;`
	var version int64
	var dirty bool
	err = pool.QueryRow(context.Background(), versionQuery).Scan(&version, &dirty)
	if err != nil {
		fmt.Println("No migration history found (this is normal if migrations haven't run)")
	} else {
		fmt.Printf("Current version: %d\n", version)
		fmt.Printf("Dirty: %v\n", dirty)
	}
}
