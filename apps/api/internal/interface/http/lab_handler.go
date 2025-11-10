package http

import (
	"net/http"
	"github.com/gin-gonic/gin"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/logger"
)

// LabHandler handles HTTP requests for lab requests
type LabHandler struct {
	labUseCase  usecase.LabUseCase
	userUseCase usecase.UserUseCase
	clerkAuth   *auth.ClerkAuth
	log         logger.Logger
}

// NewLabHandler creates a new lab handler
func NewLabHandler(
	labUseCase usecase.LabUseCase,
	userUseCase usecase.UserUseCase,
	clerkAuth *auth.ClerkAuth,
	logger logger.Logger,
) *LabHandler {
	return &LabHandler{
		labUseCase:  labUseCase,
		userUseCase: userUseCase,
		clerkAuth:   clerkAuth,
		log:         logger,
	}
}

// GetContext handles GET /api/labs/context
// Returns quick picks, guardrails, and active lab
func (h *LabHandler) GetContext(c *gin.Context) {
	// Get authenticated user
	authUser, err := auth.GetAuthUser(c)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Get user from database to check role
	user, err := h.userUseCase.GetUserByClerkID(c.Request.Context(), authUser.ClerkID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Get user role (default to user if not set)
	userRole := getUserRole(user)

	// Get context data
	context, err := h.labUseCase.GetContext(c.Request.Context(), user.ID, userRole)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"quick_picks":         context.QuickPicks,
		"guardrail_snapshot":  context.GuardrailSnapshot,
		"active_lab":          context.ActiveLab,
	})
}

// CreateDraft handles POST /api/labs/draft
// Creates a new draft lab request
func (h *LabHandler) CreateDraft(c *gin.Context) {
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
		Source      string `json:"source"`
		CVEID       string `json:"cve_id"`
		Title       string `json:"title"`
		Severity    string `json:"severity"`
		Description string `json:"description"`
		Objective   string `json:"objective"`
		TTLHours    int    `json:"ttl_hours"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		h.handleError(c, errors.NewBadRequest("Invalid request body"))
		return
	}

	// Create input
	input := &usecase.CreateLabInput{
		Source:      entity.LabSource(req.Source),
		CVEID:       req.CVEID,
		Title:       req.Title,
		Severity:    entity.LabSeverity(req.Severity),
		Description: req.Description,
		Objective:   req.Objective,
		TTLHours:    req.TTLHours,
	}

	// Create draft
	labRequest, err := h.labUseCase.CreateDraft(c.Request.Context(), user.ID, input)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"lab_request": h.serializeLabRequest(labRequest),
	})
}

// GenerateBlueprint handles POST /api/labs/:id/blueprint
// Generates a blueprint for a lab request
func (h *LabHandler) GenerateBlueprint(c *gin.Context) {
	labID := c.Param("id")
	if labID == "" {
		h.handleError(c, errors.NewBadRequest("Lab ID is required"))
		return
	}

	// Generate blueprint
	labRequest, err := h.labUseCase.GenerateBlueprint(c.Request.Context(), labID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"lab_request": h.serializeLabRequest(labRequest),
	})
}

// ConfirmRequest handles POST /api/labs/:id/confirm
// Validates guardrails and confirms a lab request
func (h *LabHandler) ConfirmRequest(c *gin.Context) {
	labID := c.Param("id")
	if labID == "" {
		h.handleError(c, errors.NewBadRequest("Lab ID is required"))
		return
	}

	// Get authenticated user
	authUser, err := auth.GetAuthUser(c)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Get user from database to check role
	user, err := h.userUseCase.GetUserByClerkID(c.Request.Context(), authUser.ClerkID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	userRole := getUserRole(user)

	// Parse request body
	var req struct {
		Justification string `json:"justification"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		// Justification is optional, so we can proceed with empty
		req.Justification = ""
	}

	// Confirm request
	labRequest, err := h.labUseCase.ConfirmRequest(
		c.Request.Context(),
		labID,
		userRole,
		req.Justification,
	)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"lab_request": h.serializeLabRequest(labRequest),
		"message":     "Lab request confirmed and queued for provisioning",
	})
}

// GetActive handles GET /api/labs/active
// Returns the active lab for the authenticated user
func (h *LabHandler) GetActive(c *gin.Context) {
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

	// Get active labs
	activeLabs, err := h.labUseCase.GetActiveByUserID(c.Request.Context(), user.ID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	if len(activeLabs) == 0 {
		c.JSON(http.StatusOK, gin.H{
			"active_lab": nil,
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"active_lab": h.serializeLabRequest(activeLabs[0]),
	})
}

// GetByID handles GET /api/labs/:id
// Returns a specific lab request by ID
func (h *LabHandler) GetByID(c *gin.Context) {
	labID := c.Param("id")
	if labID == "" {
		h.handleError(c, errors.NewBadRequest("Lab ID is required"))
		return
	}

	// Get lab request
	labRequest, err := h.labUseCase.GetByID(c.Request.Context(), labID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"lab_request": h.serializeLabRequest(labRequest),
	})
}

// CancelLab handles POST /api/labs/:id/cancel
// Cancels a running or queued lab
func (h *LabHandler) CancelLab(c *gin.Context) {
	labID := c.Param("id")
	if labID == "" {
		h.handleError(c, errors.NewBadRequest("Lab ID is required"))
		return
	}

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

	// Cancel lab
	err = h.labUseCase.CancelLab(c.Request.Context(), labID, user.ID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "Lab cancelled successfully",
	})
}

// serializeLabRequest converts a lab request entity to JSON response
func (h *LabHandler) serializeLabRequest(lab *entity.LabRequest) gin.H {
	return gin.H{
		"id":                  lab.ID,
		"user_id":             lab.UserID,
		"source":              lab.Source,
		"cve_id":              lab.CVEID,
		"title":               lab.Title,
		"severity":            lab.Severity,
		"description":         lab.Description,
		"objective":           lab.Objective,
		"ttl_hours":           lab.TTLHours,
		"expires_at":          lab.ExpiresAt,
		"status":              lab.Status,
		"blueprint":           lab.Blueprint,
		"guardrail_snapshot":  lab.GuardrailSnapshot,
		"risk_rating":         lab.RiskRating,
		"created_at":          lab.CreatedAt,
		"updated_at":          lab.UpdatedAt,
	}
}

// getUserRole extracts the user role from the user entity
// For MVP, this reads from a future "role" field we'll add to the User entity
// For now, defaults to "user" role
func getUserRole(user *entity.User) entity.UserRole {
	// TODO: Once User entity has Role field, return user.Role
	// For now, default to user role
	return entity.UserRoleUser
}

// handleError handles errors and returns appropriate HTTP responses
func (h *LabHandler) handleError(c *gin.Context, err error) {
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
