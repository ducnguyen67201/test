package temporal

import (
	"crypto/tls"
	"fmt"

	"github.com/zerozero/apps/queue/internal/config"
	"github.com/zerozero/apps/queue/pkg/logger"
	"go.temporal.io/sdk/client"
)

// NewClient creates a new Temporal client with configuration
func NewClient(cfg config.TemporalConfig, log logger.Logger) (client.Client, error) {
	options := client.Options{
		HostPort:  cfg.Address,
		Namespace: cfg.Namespace,
	}

	// Configure TLS if enabled
	if cfg.TLSEnabled {
		options.ConnectionOptions = client.ConnectionOptions{
			TLS: &tls.Config{
				MinVersion: tls.VersionTLS12,
			},
		}
	}

	// Create client
	c, err := client.Dial(options)
	if err != nil {
		log.Error("failed to create Temporal client",
			logger.String("address", cfg.Address),
			logger.String("namespace", cfg.Namespace),
			logger.Error(err))
		return nil, fmt.Errorf("failed to create Temporal client: %w", err)
	}

	log.Info("temporal client created successfully",
		logger.String("address", cfg.Address),
		logger.String("namespace", cfg.Namespace))

	return c, nil
}
