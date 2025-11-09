package router

import (
	"github.com/gin-gonic/gin"
	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/config"
	"github.com/zerozero/apps/api/pkg/logger"
)

// Dependencies holds all dependencies needed for routing
type Dependencies struct {
	UserUseCase usecase.UserUseCase // TODO: Replace with actual interface
	ClerkAuth   *auth.ClerkAuth
	Logger      logger.Logger
	Config      *config.Config
}

// RegisterRoutes sets up all application routes
func RegisterRoutes(router *gin.Engine, deps *Dependencies) {
	// Register HTTP routes
	RegisterHTTPRoutes(router, deps)

}
