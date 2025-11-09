package app

import (
	"github.com/gin-gonic/gin"
	"github.com/zerozero/apps/api/internal/router"
	"github.com/zerozero/apps/api/internal/router/middleware"
	"github.com/zerozero/apps/api/pkg/config"
)

// SetupRouter initializes and configures the Gin router
func SetupRouter(cfg *config.Config, deps *router.Dependencies) *gin.Engine {
	// Set Gin mode
	if !cfg.App.Debug {
		gin.SetMode(gin.ReleaseMode)
	}

	// Initialize router
	r := gin.New()

	// Add global middleware
	r.Use(gin.Recovery())
	r.Use(middleware.CORS(cfg.Server.CorsOrigins))
	r.Use(middleware.Logging(deps.Logger))

	// Register all routes
	router.RegisterRoutes(r, deps)

	return r
}
