package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/zerozero/apps/api/internal/app"
	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/infrastructure/db"
	"github.com/zerozero/apps/api/internal/infrastructure/services"
	"github.com/zerozero/apps/api/internal/router"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/logger"
	"go.temporal.io/sdk/client"
)

func main() {
	// Load configuration
	cfg, err := app.LoadConfig()
	if err != nil {
		log.Fatalf("Failed to load configuration: %v", err)
	}

	// Initialize logger
	logLevel := "info"
	if cfg.App.Debug {
		logLevel = "debug"
	}
	appLogger := logger.New(logLevel)
	appLogger.Info("Starting server", logger.String("environment", cfg.App.Environment))

	// Connect to database (pgxpool for backward compatibility)
	dbPool, err := app.ConnectDatabase(cfg, appLogger)
	if err != nil {
		appLogger.Fatal("Failed to connect to database", logger.Error(err))
	}
	defer dbPool.Close()

	// Connect to database with GORM
	gormDB, err := app.ConnectGORMDatabase(cfg, appLogger)
	if err != nil {
		appLogger.Fatal("Failed to connect to database with GORM", logger.Error(err))
	}

	// Initialize Clerk auth
	clerkAuth, err := auth.NewClerkAuth(cfg.Auth.ClerkSecretKey, cfg.Auth.ClerkJWKSURL, appLogger)
	if err != nil {
		appLogger.Fatal("Failed to initialize Clerk auth", logger.Error(err))
	}

	// Create Temporal client (if enabled)
	var temporalClient client.Client
	if cfg.Temporal.Enabled {
		temporalClient, err = client.Dial(client.Options{
			HostPort:  cfg.Temporal.Address,
			Namespace: cfg.Temporal.Namespace,
		})
		if err != nil {
			appLogger.Fatal("Failed to create Temporal client", logger.Error(err))
		}
		defer temporalClient.Close()
		appLogger.Info("Temporal client connected",
			logger.String("address", cfg.Temporal.Address),
			logger.String("namespace", cfg.Temporal.Namespace))
	} else {
		appLogger.Info("Temporal integration disabled")
	}

	// Initialize repositories with GORM
	userRepo := db.NewUserRepository(gormDB)
	labRepo := db.NewLabRepository(gormDB)

	// Initialize services
	blueprintService := services.NewMockBlueprintService(appLogger)

	// Initialize use cases
	userUseCase := usecase.NewUserUseCase(userRepo, appLogger)
	labUseCase := usecase.NewLabUseCase(labRepo, userRepo, blueprintService, temporalClient, cfg, appLogger)

	// Setup router with all dependencies
	deps := &router.Dependencies{
		UserUseCase: userUseCase,
		LabUseCase:  labUseCase,
		ClerkAuth:   clerkAuth,
		Logger:      appLogger,
		Config:      cfg,
	}
	r := app.SetupRouter(cfg, deps)

	// Start server
	srv := &http.Server{
		Addr:         fmt.Sprintf(":%d", cfg.Server.Port),
		Handler:      r,
		ReadTimeout:  time.Duration(cfg.Server.ReadTimeout) * time.Second,
		WriteTimeout: time.Duration(cfg.Server.WriteTimeout) * time.Second,
	}

	// Graceful shutdown
	go func() {
		appLogger.Info("Server started", logger.Int("port", cfg.Server.Port))
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			appLogger.Fatal("Failed to start server", logger.Error(err))
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	appLogger.Info("Shutting down server...")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		appLogger.Fatal("Server forced to shutdown", logger.Error(err))
	}

	appLogger.Info("Server shutdown complete")
}
