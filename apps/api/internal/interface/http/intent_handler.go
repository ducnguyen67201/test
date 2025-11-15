package http

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/logger"
)

// IntentHandler handles HTTP requests for intents
type IntentHandler struct {
	intentUseCase usecase.IntentUseCase
	userUseCase   usecase.UserUseCase
	clerkAuth     *auth.ClerkAuth
	log           logger.Logger
}

// NewIntentHandler creates a new intent handler
func NewIntentHandler(
	intentUseCase usecase.IntentUseCase,
	userUseCase usecase.UserUseCase,
	clerkAuth *auth.ClerkAuth,
	logger logger.Logger,
) *IntentHandler {
	return &IntentHandler{
		intentUseCase: intentUseCase,
		userUseCase:   userUseCase,
		clerkAuth:     clerkAuth,
		log:           logger,
	}
}

// GetByID handles GET /api/intents/:id
// Returns a specific intent by ID
func (h *IntentHandler) GetByID(c *gin.Context) {
	intentID := c.Param("id")
	if intentID == "" {
		h.handleError(c, errors.NewBadRequest("Intent ID is required"))
		return
	}

	// Get intent
	intent, err := h.intentUseCase.GetByID(c.Request.Context(), intentID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"intent": h.serializeIntent(intent),
	})
}

// GetBySessionID handles GET /api/intents/session/:session_id
// Returns the intent for a specific session
func (h *IntentHandler) GetBySessionID(c *gin.Context) {
	sessionID := c.Param("session_id")
	if sessionID == "" {
		h.handleError(c, errors.NewBadRequest("Session ID is required"))
		return
	}

	// Get intent
	intent, err := h.intentUseCase.GetBySessionID(c.Request.Context(), sessionID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"intent": h.serializeIntent(intent),
	})
}

// GetPending handles GET /api/intents/pending
// Returns pending intents awaiting approval
func (h *IntentHandler) GetPending(c *gin.Context) {
	// Parse pagination parameters
	limit := h.getQueryInt(c, "limit", 20)
	offset := h.getQueryInt(c, "offset", 0)

	// Get pending intents
	intents, err := h.intentUseCase.GetPendingIntents(c.Request.Context(), limit, offset)
	if err != nil {
		h.handleError(c, err)
		return
	}

	serialized := make([]gin.H, len(intents))
	for i, intent := range intents {
		serialized[i] = h.serializeIntent(intent)
	}

	c.JSON(http.StatusOK, gin.H{
		"intents": serialized,
		"count":   len(serialized),
	})
}

// Approve handles POST /api/intents/:id/approve
// Approves an intent
func (h *IntentHandler) Approve(c *gin.Context) {
	intentID := c.Param("id")
	if intentID == "" {
		h.handleError(c, errors.NewBadRequest("Intent ID is required"))
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

	// Approve intent
	approvedIntent, err := h.intentUseCase.Approve(c.Request.Context(), intentID, user.ID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"intent":  h.serializeIntent(approvedIntent),
		"message": "Intent approved successfully",
	})
}

// Reject handles POST /api/intents/:id/reject
// Rejects an intent
func (h *IntentHandler) Reject(c *gin.Context) {
	intentID := c.Param("id")
	if intentID == "" {
		h.handleError(c, errors.NewBadRequest("Intent ID is required"))
		return
	}

	// Parse request body
	var req struct {
		Reason string `json:"reason" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		h.handleError(c, errors.NewBadRequest("Rejection reason is required"))
		return
	}

	// Reject intent
	rejectedIntent, err := h.intentUseCase.Reject(c.Request.Context(), intentID, req.Reason)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"intent":  h.serializeIntent(rejectedIntent),
		"message": "Intent rejected successfully",
	})
}

// Validate handles POST /api/intents/:id/validate
// Validates an intent against guardrails
func (h *IntentHandler) Validate(c *gin.Context) {
	intentID := c.Param("id")
	if intentID == "" {
		h.handleError(c, errors.NewBadRequest("Intent ID is required"))
		return
	}

	// Get intent
	intent, err := h.intentUseCase.GetByID(c.Request.Context(), intentID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Validate intent
	validationResult, err := h.intentUseCase.ValidateIntent(c.Request.Context(), intent)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"validation_result": gin.H{
			"passed":   validationResult.Passed,
			"errors":   validationResult.Errors,
			"warnings": validationResult.Warnings,
			"payload":  validationResult.Payload,
		},
	})
}

// GetPayload handles GET /api/intents/:id/payload
// Returns the parsed intent payload
func (h *IntentHandler) GetPayload(c *gin.Context) {
	intentID := c.Param("id")
	if intentID == "" {
		h.handleError(c, errors.NewBadRequest("Intent ID is required"))
		return
	}

	// Get intent payload
	payload, err := h.intentUseCase.GetIntentPayload(c.Request.Context(), intentID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"payload": payload,
	})
}

// serializeIntent converts an intent entity to JSON response
func (h *IntentHandler) serializeIntent(intent *entity.Intent) gin.H {
	// Parse payload for better JSON output
	var payload map[string]interface{}
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		payload = nil
	}

	var validatorErrors map[string]interface{}
	if len(intent.ValidatorErrors) > 0 {
		if err := json.Unmarshal(intent.ValidatorErrors, &validatorErrors); err != nil {
			validatorErrors = nil
		}
	}

	return gin.H{
		"id":               intent.ID,
		"session_id":       intent.SessionID,
		"payload":          payload,
		"confidence":       intent.Confidence,
		"status":           intent.Status,
		"validator_errors": validatorErrors,
		"created_at":       intent.CreatedAt,
		"updated_at":       intent.UpdatedAt,
	}
}

// getQueryInt extracts an integer query parameter with a default value
func (h *IntentHandler) getQueryInt(c *gin.Context, key string, defaultValue int) int {
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
func (h *IntentHandler) handleError(c *gin.Context, err error) {
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
