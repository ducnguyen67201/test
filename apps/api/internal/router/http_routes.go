package router

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	httphandler "github.com/zerozero/apps/api/internal/interface/http"
)

// RegisterHTTPRoutes sets up all HTTP/REST API routes
func RegisterHTTPRoutes(router *gin.Engine, deps *Dependencies) {
	// Health check endpoint (no auth required)
	router.GET("/health", healthCheckHandler)

	// API routes with authentication
	api := router.Group("/api")
	api.Use(deps.ClerkAuth.Middleware())
	{
		// User routes
		registerUserRoutes(api, deps)

		// Lab routes
		registerLabRoutes(api, deps)
	}
}

// healthCheckHandler returns server health status
func healthCheckHandler(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status": "healthy",
		"time":   time.Now(),
	})
}

// registerUserRoutes sets up user-related routes
func registerUserRoutes(api *gin.RouterGroup, deps *Dependencies) {
	userHandler := httphandler.NewUserHandler(deps.UserUseCase, deps.ClerkAuth, deps.Logger)
	api.GET("/me", userHandler.GetMe)
	api.PATCH("/me", userHandler.UpdateProfile)
}

// registerLabRoutes sets up lab request-related routes
func registerLabRoutes(api *gin.RouterGroup, deps *Dependencies) {
	labHandler := httphandler.NewLabHandler(deps.LabUseCase, deps.UserUseCase, deps.ClerkAuth, deps.Logger)

	// Lab context and management
	labs := api.Group("/labs")
	{
		labs.GET("/context", labHandler.GetContext)
		labs.GET("/active", labHandler.GetActive)
		labs.GET("/:id", labHandler.GetByID)

		labs.POST("/draft", labHandler.CreateDraft)
		labs.POST("/:id/blueprint", labHandler.GenerateBlueprint)
		labs.POST("/:id/confirm", labHandler.ConfirmRequest)
		labs.POST("/:id/cancel", labHandler.CancelLab)
	}
}
