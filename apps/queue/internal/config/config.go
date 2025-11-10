package config

import (
	"log"
	"os"
	"path/filepath"
	"strconv"

	"github.com/joho/godotenv"
)

// Config holds all queue service configuration
type Config struct {
	Temporal    TemporalConfig
	API         APIConfig
	Provisioner ProvisionerConfig
	Logger      LoggerConfig
}

// TemporalConfig holds Temporal workflow configuration
type TemporalConfig struct {
	Address        string
	Namespace      string
	LabsTaskQueue  string
	WorkerIdentity string
	TLSEnabled     bool
	Enabled        bool
}

// APIConfig holds apps/api gRPC configuration
type APIConfig struct {
	GRPCAddress string
	GRPCPort    int
	TLSEnabled  bool
}

// ProvisionerConfig holds provisioner service configuration
type ProvisionerConfig struct {
	GRPCAddress string
	TLSEnabled  bool
}

// LoggerConfig holds logger configuration
type LoggerConfig struct {
	Level string
	Debug bool
}

// Load loads configuration from environment variables
func Load() (*Config, error) {
	// Load .env.local from root directory
	rootDir := getRootDir()
	envPath := filepath.Join(rootDir, ".env.local")

	if err := godotenv.Load(envPath); err != nil {
		log.Printf("Warning: .env.local file not found at: %s", envPath)
	} else {
		log.Printf("Loaded environment from: %s", envPath)
	}

	config := &Config{
		Temporal: TemporalConfig{
			Address:        getEnv("TEMPORAL_ADDRESS", "localhost:7233"),
			Namespace:      getEnv("TEMPORAL_NAMESPACE", "zerozero-dev"),
			LabsTaskQueue:  getEnv("TEMPORAL_LABS_TASK_QUEUE", "labs.provisioning.v1"),
			WorkerIdentity: getEnv("TEMPORAL_WORKER_IDENTITY", "queue-worker"),
			TLSEnabled:     getEnvBool("TEMPORAL_TLS_ENABLED", false),
			Enabled:        getEnvBool("TEMPORAL_ENABLED", true),
		},
		API: APIConfig{
			GRPCAddress: getEnv("API_GRPC_ADDRESS", "localhost:50051"),
			GRPCPort:    getEnvInt("API_GRPC_PORT", 50051),
			TLSEnabled:  getEnvBool("API_GRPC_TLS_ENABLED", false),
		},
		Provisioner: ProvisionerConfig{
			GRPCAddress: getEnv("PROVISIONER_GRPC_ADDRESS", "localhost:50052"),
			TLSEnabled:  getEnvBool("PROVISIONER_GRPC_TLS_ENABLED", false),
		},
		Logger: LoggerConfig{
			Level: getEnv("LOG_LEVEL", "info"),
			Debug: getEnvBool("APP_DEBUG", false),
		},
	}

	return config, nil
}

// getRootDir finds the git root directory by walking up the directory tree
func getRootDir() string {
	dir, err := os.Getwd()
	if err != nil {
		return "."
	}

	// Walk up the directory tree to find git root or go.work
	for {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return dir
		}
		if _, err := os.Stat(filepath.Join(dir, "go.work")); err == nil {
			return dir
		}

		parent := filepath.Dir(dir)
		if parent == dir {
			// Reached filesystem root
			return "."
		}
		dir = parent
	}
}

// Helper functions
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvInt(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if intValue, err := strconv.Atoi(value); err == nil {
			return intValue
		}
	}
	return defaultValue
}

func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		if boolValue, err := strconv.ParseBool(value); err == nil {
			return boolValue
		}
	}
	return defaultValue
}
