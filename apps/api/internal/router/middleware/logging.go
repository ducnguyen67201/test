package middleware

import (
	"time"

	"github.com/gin-gonic/gin"
	"github.com/zerozero/apps/api/pkg/logger"
)

// Logging logs requests
func Logging(log logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		raw := c.Request.URL.RawQuery

		// Process request
		c.Next()

		// Skip health check logging
		if path == "/health" {
			return
		}

		latency := time.Since(start)
		if raw != "" {
			path = path + "?" + raw
		}

		log.Info("Request processed",
			logger.String("method", c.Request.Method),
			logger.String("path", path),
			logger.Int("status", c.Writer.Status()),
			logger.String("latency", latency.String()),
			logger.String("ip", c.ClientIP()),
		)
	}
}
