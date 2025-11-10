package config

import (
    "os"
    "strconv"
    "strings"
)

// Config holds all application configuration
type Config struct {
    App      AppConfig
    Database DatabaseConfig
    Redis    RedisConfig
    Auth     AuthConfig
    Server   ServerConfig
    Temporal TemporalConfig
}

// AppConfig holds application-specific configuration
type AppConfig struct {
    Name        string
    Environment string
    Debug       bool
}

// DatabaseConfig holds database configuration
type DatabaseConfig struct {
    URL             string
    MaxConnections  int
    MaxIdleConns    int
    ConnMaxLifetime int
}

// RedisConfig holds Redis configuration
type RedisConfig struct {
    URL string
}

// AuthConfig holds authentication configuration
type AuthConfig struct {
    ClerkSecretKey     string
    ClerkWebhookSecret string
    ClerkJWKSURL       string
}

// ServerConfig holds server configuration
type ServerConfig struct {
    Port         int
    GRPCPort     int
    CorsOrigins  []string
    ReadTimeout  int
    WriteTimeout int
}

// TemporalConfig holds Temporal workflow configuration
type TemporalConfig struct {
    Address       string
    Namespace     string
    LabsTaskQueue string
    Enabled       bool
}

// Load loads configuration from environment variables
func Load() (*Config, error) {
    config := &Config{
        App: AppConfig{
            Name:        getEnv("APP_NAME", "zerozero-api"),
            Environment: getEnv("APP_ENV", "development"),
            Debug:       getEnvBool("APP_DEBUG", true),
        },
        Database: DatabaseConfig{
            URL:             getEnv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable"),
            MaxConnections:  getEnvInt("DB_MAX_CONNECTIONS", 25),
            MaxIdleConns:    getEnvInt("DB_MAX_IDLE_CONNS", 5),
            ConnMaxLifetime: getEnvInt("DB_CONN_MAX_LIFETIME", 300),
        },
        Redis: RedisConfig{
            URL: getEnv("REDIS_URL", "redis://localhost:6379"),
        },
        Auth: AuthConfig{
            ClerkSecretKey:     getEnv("CLERK_SECRET_KEY", ""),
            ClerkWebhookSecret: getEnv("CLERK_WEBHOOK_SECRET", ""),
            ClerkJWKSURL:       getEnv("CLERK_JWKS_URL", "https://teaching-camel-82.clerk.accounts.dev/.well-known/jwks.json"),
        },
        Server: ServerConfig{
            Port:         getEnvInt("API_PORT", 8080),
            GRPCPort:     getEnvInt("GRPC_PORT", 9090),
            CorsOrigins:  strings.Split(getEnv("API_CORS_ORIGINS", "http://localhost:3000"), ","),
            ReadTimeout:  getEnvInt("SERVER_READ_TIMEOUT", 10),
            WriteTimeout: getEnvInt("SERVER_WRITE_TIMEOUT", 10),
        },
        Temporal: TemporalConfig{
            Address:       getEnv("TEMPORAL_ADDRESS", "localhost:7233"),
            Namespace:     getEnv("TEMPORAL_NAMESPACE", "zerozero-dev"),
            LabsTaskQueue: getEnv("TEMPORAL_LABS_TASK_QUEUE", "labs.provisioning.v1"),
            Enabled:       getEnvBool("TEMPORAL_ENABLED", false),
        },
    }

    return config, nil
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