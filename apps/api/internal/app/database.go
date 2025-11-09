package app

import (
	"context"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/zerozero/apps/api/pkg/config"
	"github.com/zerozero/apps/api/pkg/logger"
)

// ConnectDatabase establishes a connection to the database
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

	log.Info("Connected to database")
	return dbPool, nil
}
