package app

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/zerozero/apps/api/pkg/config"
	"github.com/zerozero/apps/api/pkg/logger"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"
)

// ConnectDatabase establishes a connection to the database using pgxpool
// Kept for backward compatibility
func ConnectDatabase(cfg *config.Config, log logger.Logger) (*pgxpool.Pool, error) {
	// Connect to database
	dbPool, err := pgxpool.New(context.Background(), cfg.Database.URL)
	if err != nil {
		return nil, err
	}

	// Ping database to verify connection
	if err := dbPool.Ping(context.Background()); err != nil {
		dbPool.Close()
		return nil, err
	}

	log.Info("Connected to database (pgxpool)")
	return dbPool, nil
}

// ConnectGORMDatabase establishes a GORM connection to the database
func ConnectGORMDatabase(cfg *config.Config, log logger.Logger) (*gorm.DB, error) {
	// Configure GORM logger
	gormLogLevel := gormlogger.Info
	if cfg.App.Environment == "production" {
		gormLogLevel = gormlogger.Warn
	}

	gormConfig := &gorm.Config{
		Logger: gormlogger.Default.LogMode(gormLogLevel),
	}

	// Connect to database using GORM with PostgreSQL driver
	db, err := gorm.Open(postgres.Open(cfg.Database.URL), gormConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database with GORM: %w", err)
	}

	// Get underlying SQL DB for connection pool settings
	sqlDB, err := db.DB()
	if err != nil {
		return nil, fmt.Errorf("failed to get underlying SQL DB: %w", err)
	}

	// Configure connection pool
	sqlDB.SetMaxOpenConns(25)
	sqlDB.SetMaxIdleConns(5)

	// Ping database to verify connection
	if err := sqlDB.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	log.Info("Connected to database (GORM)")
	return db, nil
}
