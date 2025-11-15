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

		// Chat routes
		registerChatRoutes(api, deps)

		// Recipe routes
		registerRecipeRoutes(api, deps)

		// Intent routes
		registerIntentRoutes(api, deps)
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

// registerChatRoutes sets up chat session-related routes
func registerChatRoutes(api *gin.RouterGroup, deps *Dependencies) {
	chatHandler := httphandler.NewChatHandler(deps.ChatUseCase, deps.UserUseCase, deps.ClerkAuth, deps.Logger)

	// Chat session management
	chat := api.Group("/chat")
	{
		// Session CRUD
		chat.POST("/sessions", chatHandler.CreateSession)
		chat.GET("/sessions", chatHandler.GetUserSessions)
		chat.GET("/sessions/active", chatHandler.GetActiveSessions)
		chat.GET("/sessions/:id", chatHandler.GetSession)
		chat.GET("/sessions/:id/messages", chatHandler.GetSessionWithMessages)
		chat.DELETE("/sessions/:id", chatHandler.DeleteSession)

		// Messaging
		chat.POST("/sessions/:id/messages", chatHandler.SendMessage)
		chat.GET("/sessions/:id/stream", chatHandler.StreamMessage)

		// Session lifecycle
		chat.POST("/sessions/:id/finalize", chatHandler.FinalizeSession)
		chat.POST("/sessions/:id/close", chatHandler.CloseSession)
	}
}

// registerRecipeRoutes sets up recipe-related routes
func registerRecipeRoutes(api *gin.RouterGroup, deps *Dependencies) {
	recipeHandler := httphandler.NewRecipeHandler(deps.RecipeUseCase, deps.UserUseCase, deps.ClerkAuth, deps.Logger)

	// Recipe management
	recipes := api.Group("/recipes")
	{
		// Recipe CRUD
		recipes.POST("", recipeHandler.CreateManual)
		recipes.POST("/from-intent", recipeHandler.CreateFromIntent)
		recipes.GET("", recipeHandler.List)
		recipes.GET("/search", recipeHandler.Search)
		recipes.GET("/:id", recipeHandler.GetByID)
		recipes.PUT("/:id", recipeHandler.Update)
		recipes.DELETE("/:id", recipeHandler.Delete)

		// Recipe actions
		recipes.POST("/:id/activate", recipeHandler.Activate)
		recipes.POST("/:id/deactivate", recipeHandler.Deactivate)
		recipes.POST("/:id/enrich-cve", recipeHandler.EnrichWithCVE)
		recipes.POST("/:id/validate", recipeHandler.Validate)
	}
}

// registerIntentRoutes sets up intent-related routes
func registerIntentRoutes(api *gin.RouterGroup, deps *Dependencies) {
	intentHandler := httphandler.NewIntentHandler(deps.IntentUseCase, deps.UserUseCase, deps.ClerkAuth, deps.Logger)

	// Intent management
	intents := api.Group("/intents")
	{
		// Intent retrieval
		intents.GET("/pending", intentHandler.GetPending)
		intents.GET("/:id", intentHandler.GetByID)
		intents.GET("/session/:session_id", intentHandler.GetBySessionID)
		intents.GET("/:id/payload", intentHandler.GetPayload)

		// Intent approval workflow
		intents.POST("/:id/approve", intentHandler.Approve)
		intents.POST("/:id/reject", intentHandler.Reject)
		intents.POST("/:id/validate", intentHandler.Validate)
	}
}
