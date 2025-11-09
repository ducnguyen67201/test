package app

import (
	"log"
	"os"
	"path/filepath"

	"github.com/joho/godotenv"
	"github.com/zerozero/apps/api/pkg/config"
)

// getRootDir finds the git root directory
func getRootDir() string {
	dir, err := os.Getwd()
	if err != nil {
		return "."
	}

	// Walk up the directory tree to find git root
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

// LoadConfig loads environment variables and application configuration
func LoadConfig() (*config.Config, error) {
	// Load environment variables from root directory using absolute path
	rootDir := getRootDir()
	envPath := filepath.Join(rootDir, ".env.local")

	if err := godotenv.Load(envPath); err != nil {
		log.Printf("Warning: .env.local file not found at: %s", envPath)
	} else {
		log.Printf("Loaded environment from: %s", envPath)
	}

	// Load configuration
	cfg, err := config.Load()
	if err != nil {
		return nil, err
	}

	return cfg, nil
}
