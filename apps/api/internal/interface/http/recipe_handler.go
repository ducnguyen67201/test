package http

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/logger"
)

// RecipeHandler handles HTTP requests for recipes
type RecipeHandler struct {
	recipeUseCase usecase.RecipeUseCase
	userUseCase   usecase.UserUseCase
	clerkAuth     *auth.ClerkAuth
	log           logger.Logger
}

// NewRecipeHandler creates a new recipe handler
func NewRecipeHandler(
	recipeUseCase usecase.RecipeUseCase,
	userUseCase usecase.UserUseCase,
	clerkAuth *auth.ClerkAuth,
	logger logger.Logger,
) *RecipeHandler {
	return &RecipeHandler{
		recipeUseCase: recipeUseCase,
		userUseCase:   userUseCase,
		clerkAuth:     clerkAuth,
		log:           logger,
	}
}

// CreateFromIntent handles POST /api/recipes/from-intent
// Creates a recipe from an approved intent
func (h *RecipeHandler) CreateFromIntent(c *gin.Context) {
	// Get authenticated user
	authUser, err := auth.GetAuthUser(c)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Get user from database
	user, err := h.userUseCase.GetUserByClerkID(c.Request.Context(), authUser.ClerkID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Parse request body
	var req struct {
		IntentID string `json:"intent_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		h.handleError(c, errors.NewBadRequest("Intent ID is required"))
		return
	}

	// Create recipe from intent
	recipe, err := h.recipeUseCase.CreateFromIntent(c.Request.Context(), req.IntentID, user.ID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"recipe":  h.serializeRecipe(recipe),
		"message": "Recipe created from intent successfully",
	})
}

// CreateManual handles POST /api/recipes
// Creates a recipe manually
func (h *RecipeHandler) CreateManual(c *gin.Context) {
	// Get authenticated user
	authUser, err := auth.GetAuthUser(c)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Get user from database
	user, err := h.userUseCase.GetUserByClerkID(c.Request.Context(), authUser.ClerkID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Parse request body
	var req struct {
		Name                string                 `json:"name" binding:"required"`
		Description         string                 `json:"description"`
		Software            string                 `json:"software" binding:"required"`
		VersionConstraint   string                 `json:"version_constraint"`
		OS                  string                 `json:"os"`
		Packages            []entity.RecipePackage `json:"packages"`
		NetworkRequirements string                 `json:"network_requirements"`
		ComplianceControls  []string               `json:"compliance_controls"`
		ValidationChecks    []string               `json:"validation_checks"`
		IsActive            bool                   `json:"is_active"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		h.handleError(c, errors.NewBadRequest("Invalid request body"))
		return
	}

	// Create input
	input := &usecase.CreateRecipeInput{
		Name:                req.Name,
		Description:         req.Description,
		Software:            req.Software,
		VersionConstraint:   req.VersionConstraint,
		OS:                  req.OS,
		Packages:            req.Packages,
		NetworkRequirements: req.NetworkRequirements,
		ComplianceControls:  req.ComplianceControls,
		ValidationChecks:    req.ValidationChecks,
		IsActive:            req.IsActive,
	}

	// Create recipe
	recipe, err := h.recipeUseCase.CreateManual(c.Request.Context(), input, user.ID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"recipe":  h.serializeRecipe(recipe),
		"message": "Recipe created successfully",
	})
}

// GetByID handles GET /api/recipes/:id
// Returns a specific recipe by ID
func (h *RecipeHandler) GetByID(c *gin.Context) {
	recipeID := c.Param("id")
	if recipeID == "" {
		h.handleError(c, errors.NewBadRequest("Recipe ID is required"))
		return
	}

	// Get recipe
	recipe, err := h.recipeUseCase.GetByID(c.Request.Context(), recipeID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"recipe": h.serializeRecipe(recipe),
	})
}

// List handles GET /api/recipes
// Returns a list of recipes with optional filtering
func (h *RecipeHandler) List(c *gin.Context) {
	// Parse query parameters
	limit := h.getQueryInt(c, "limit", 20)
	offset := h.getQueryInt(c, "offset", 0)
	software := c.Query("software")

	var recipes []*entity.Recipe
	var err error

	// Get recipes based on filters
	if software != "" {
		recipes, err = h.recipeUseCase.GetBySoftware(c.Request.Context(), software, limit, offset)
	} else {
		// Default to active recipes when no filter specified
		recipes, err = h.recipeUseCase.GetActive(c.Request.Context(), limit, offset)
	}

	if err != nil {
		h.handleError(c, err)
		return
	}

	serialized := make([]gin.H, len(recipes))
	for i, recipe := range recipes {
		serialized[i] = h.serializeRecipe(recipe)
	}

	c.JSON(http.StatusOK, gin.H{
		"recipes": serialized,
		"count":   len(serialized),
	})
}

// Search handles GET /api/recipes/search
// Searches recipes by query string
func (h *RecipeHandler) Search(c *gin.Context) {
	query := c.Query("q")
	if query == "" {
		h.handleError(c, errors.NewBadRequest("Search query is required"))
		return
	}

	limit := h.getQueryInt(c, "limit", 20)
	offset := h.getQueryInt(c, "offset", 0)

	// Search recipes
	recipes, err := h.recipeUseCase.Search(c.Request.Context(), query, limit, offset)
	if err != nil {
		h.handleError(c, err)
		return
	}

	serialized := make([]gin.H, len(recipes))
	for i, recipe := range recipes {
		serialized[i] = h.serializeRecipe(recipe)
	}

	c.JSON(http.StatusOK, gin.H{
		"recipes": serialized,
		"count":   len(serialized),
		"query":   query,
	})
}

// Update handles PUT /api/recipes/:id
// Updates a recipe
func (h *RecipeHandler) Update(c *gin.Context) {
	recipeID := c.Param("id")
	if recipeID == "" {
		h.handleError(c, errors.NewBadRequest("Recipe ID is required"))
		return
	}

	// Parse request body
	var req struct {
		Name                *string  `json:"name"`
		Description         *string  `json:"description"`
		NetworkRequirements *string  `json:"network_requirements"`
		ComplianceControls  []string `json:"compliance_controls"`
		ValidationChecks    []string `json:"validation_checks"`
		IsActive            *bool    `json:"is_active"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		h.handleError(c, errors.NewBadRequest("Invalid request body"))
		return
	}

	// Create update input
	input := &usecase.UpdateRecipeInput{
		Name:                req.Name,
		Description:         req.Description,
		NetworkRequirements: req.NetworkRequirements,
		ComplianceControls:  req.ComplianceControls,
		ValidationChecks:    req.ValidationChecks,
		IsActive:            req.IsActive,
	}

	// Update recipe
	updatedRecipe, err := h.recipeUseCase.Update(c.Request.Context(), recipeID, input)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"recipe":  h.serializeRecipe(updatedRecipe),
		"message": "Recipe updated successfully",
	})
}

// Delete handles DELETE /api/recipes/:id
// Deletes a recipe
func (h *RecipeHandler) Delete(c *gin.Context) {
	recipeID := c.Param("id")
	if recipeID == "" {
		h.handleError(c, errors.NewBadRequest("Recipe ID is required"))
		return
	}

	// Delete recipe
	err := h.recipeUseCase.Delete(c.Request.Context(), recipeID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "Recipe deleted successfully",
	})
}

// Activate handles POST /api/recipes/:id/activate
// Activates a recipe
func (h *RecipeHandler) Activate(c *gin.Context) {
	recipeID := c.Param("id")
	if recipeID == "" {
		h.handleError(c, errors.NewBadRequest("Recipe ID is required"))
		return
	}

	// Activate recipe
	err := h.recipeUseCase.Activate(c.Request.Context(), recipeID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "Recipe activated successfully",
	})
}

// Deactivate handles POST /api/recipes/:id/deactivate
// Deactivates a recipe
func (h *RecipeHandler) Deactivate(c *gin.Context) {
	recipeID := c.Param("id")
	if recipeID == "" {
		h.handleError(c, errors.NewBadRequest("Recipe ID is required"))
		return
	}

	// Deactivate recipe
	err := h.recipeUseCase.Deactivate(c.Request.Context(), recipeID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "Recipe deactivated successfully",
	})
}

// EnrichWithCVE handles POST /api/recipes/:id/enrich-cve
// Enriches a recipe with CVE data (fetches CVE data automatically from recipe's CVE reference)
func (h *RecipeHandler) EnrichWithCVE(c *gin.Context) {
	recipeID := c.Param("id")
	if recipeID == "" {
		h.handleError(c, errors.NewBadRequest("Recipe ID is required"))
		return
	}

	// Enrich with CVE data
	recipe, err := h.recipeUseCase.EnrichWithCVEData(c.Request.Context(), recipeID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"recipe":  h.serializeRecipe(recipe),
		"message": "Recipe enriched with CVE data successfully",
	})
}

// Validate handles POST /api/recipes/:id/validate
// Validates a recipe against guardrails
func (h *RecipeHandler) Validate(c *gin.Context) {
	recipeID := c.Param("id")
	if recipeID == "" {
		h.handleError(c, errors.NewBadRequest("Recipe ID is required"))
		return
	}

	// Get recipe
	recipe, err := h.recipeUseCase.GetByID(c.Request.Context(), recipeID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Validate recipe
	validationResult, err := h.recipeUseCase.ValidateRecipe(c.Request.Context(), recipe)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"validation_result": gin.H{
			"passed":   validationResult.Passed,
			"errors":   validationResult.Errors,
			"warnings": validationResult.Warnings,
		},
	})
}

// serializeRecipe converts a recipe entity to JSON response
func (h *RecipeHandler) serializeRecipe(recipe *entity.Recipe) gin.H {
	// Parse JSONB fields for better output
	packages, _ := recipe.GetPackages()
	cveData, _ := recipe.GetCVEData()
	complianceControls, _ := recipe.GetComplianceControls()
	validationChecks, _ := recipe.GetValidationChecks()
	sourceURLs, _ := recipe.GetSourceURLs()

	return gin.H{
		"id":                  recipe.ID,
		"intent_id":           recipe.IntentID,
		"name":                recipe.Name,
		"description":         recipe.Description,
		"software":            recipe.Software,
		"os":                  recipe.OS,
		"packages":            packages,
		"cve_data":            cveData,
		"compliance_controls": complianceControls,
		"validation_checks":   validationChecks,
		"source_urls":         sourceURLs,
		"is_active":           recipe.IsActive,
		"created_by":          recipe.CreatedBy,
		"created_at":          recipe.CreatedAt,
		"updated_at":          recipe.UpdatedAt,
	}
}

// getQueryInt extracts an integer query parameter with a default value
func (h *RecipeHandler) getQueryInt(c *gin.Context, key string, defaultValue int) int {
	valueStr := c.Query(key)
	if valueStr == "" {
		return defaultValue
	}
	value, err := strconv.Atoi(valueStr)
	if err != nil {
		return defaultValue
	}
	return value
}

// handleError handles errors and returns appropriate HTTP responses
func (h *RecipeHandler) handleError(c *gin.Context, err error) {
	if appErr, ok := err.(*errors.AppError); ok {
		c.JSON(appErr.StatusCode, gin.H{
			"error": gin.H{
				"code":     appErr.Code,
				"message":  appErr.Message,
				"details":  appErr.Details,
				"metadata": appErr.Metadata,
			},
		})
		return
	}

	// Default to internal server error
	h.log.Error("Unhandled error", logger.Error(err))
	c.JSON(http.StatusInternalServerError, gin.H{
		"error": gin.H{
			"code":    "INTERNAL_ERROR",
			"message": "An unexpected error occurred",
		},
	})
}
