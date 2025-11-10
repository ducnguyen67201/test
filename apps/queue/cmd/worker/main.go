package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/zerozero/apps/queue/internal/clients"
	"github.com/zerozero/apps/queue/internal/config"
	"github.com/zerozero/apps/queue/internal/temporal"
	"github.com/zerozero/apps/queue/internal/temporal/registry"
	"github.com/zerozero/apps/queue/internal/workflows/lab"
	"github.com/zerozero/apps/queue/pkg/logger"
	"go.temporal.io/sdk/worker"
)

func main() {
	// Load configuration from root .env.local
	cfg, err := config.Load()
	if err != nil {
		log.Fatal("failed to load config:", err)
	}

	// Initialize logger
	logLevel := cfg.Logger.Level
	if cfg.Logger.Debug {
		logLevel = "debug"
	}
	appLogger := logger.New(logLevel)

	appLogger.Info("Starting Temporal worker",
		logger.String("task_queue", cfg.Temporal.LabsTaskQueue),
		logger.String("namespace", cfg.Temporal.Namespace))

	// Create Temporal client
	temporalClient, err := temporal.NewClient(cfg.Temporal, appLogger)
	if err != nil {
		appLogger.Fatal("failed to create Temporal client", logger.Error(err))
	}
	defer temporalClient.Close()

	appLogger.Info("Temporal client connected",
		logger.String("address", cfg.Temporal.Address),
		logger.String("namespace", cfg.Temporal.Namespace))

	// Create gRPC clients
	apiClient, err := clients.NewAPIClient(cfg.API.GRPCAddress, appLogger)
	if err != nil {
		appLogger.Fatal("failed to create API gRPC client", logger.Error(err))
	}
	defer apiClient.Close()

	provisionerClient, err := clients.NewProvisionerClient(cfg.Provisioner.GRPCAddress, appLogger)
	if err != nil {
		// Non-fatal - provisioner may not be running yet
		appLogger.Warn("provisioner client creation failed (continuing anyway)", logger.Error(err))
	}
	if provisionerClient != nil {
		defer provisionerClient.Close()
	}

	// Create worker for labs task queue
	w := worker.New(temporalClient, cfg.Temporal.LabsTaskQueue, worker.Options{
		Identity: cfg.Temporal.WorkerIdentity,
	})

	// Create registrars with dependencies
	labRegistrar := lab.NewRegistrar(apiClient, provisionerClient, appLogger, cfg.Temporal.LabsTaskQueue)

	// Register all workflows/activities
	registry.RegisterAll(w, []registry.Registrar{labRegistrar}, cfg.Temporal.LabsTaskQueue)

	appLogger.Info("workflows and activities registered",
		logger.String("task_queue", cfg.Temporal.LabsTaskQueue))

	// Start worker in goroutine
	go func() {
		appLogger.Info("worker started", logger.String("task_queue", cfg.Temporal.LabsTaskQueue))
		err = w.Run(worker.InterruptCh())
		if err != nil {
			appLogger.Fatal("worker failed", logger.Error(err))
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	appLogger.Info("shutting down worker...")
	w.Stop()
	appLogger.Info("worker shutdown complete")
}
