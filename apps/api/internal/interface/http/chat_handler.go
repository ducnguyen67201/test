package http

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/logger"
)

// ChatHandler handles HTTP requests for chat sessions
type ChatHandler struct {
	chatUseCase usecase.ChatUseCase
	userUseCase usecase.UserUseCase
	clerkAuth   *auth.ClerkAuth
	log         logger.Logger
}

// NewChatHandler creates a new chat handler
func NewChatHandler(
	chatUseCase usecase.ChatUseCase,
	userUseCase usecase.UserUseCase,
	clerkAuth *auth.ClerkAuth,
	logger logger.Logger,
) *ChatHandler {
	return &ChatHandler{
		chatUseCase: chatUseCase,
		userUseCase: userUseCase,
		clerkAuth:   clerkAuth,
		log:         logger,
	}
}

// CreateSession handles POST /api/chat/sessions
// Creates a new chat session
func (h *ChatHandler) CreateSession(c *gin.Context) {
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
		ProjectID *string `json:"project_id"`
		Model     string  `json:"model"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		// Model is optional, will default in use case
	}

	// Create session
	session, err := h.chatUseCase.CreateSession(c.Request.Context(), user.ID, req.ProjectID, req.Model)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"session": h.serializeChatSession(session),
	})
}

// GetSession handles GET /api/chat/sessions/:id
// Returns a specific chat session
func (h *ChatHandler) GetSession(c *gin.Context) {
	sessionID := c.Param("id")
	if sessionID == "" {
		h.handleError(c, errors.NewBadRequest("Session ID is required"))
		return
	}

	// Get session
	session, err := h.chatUseCase.GetSession(c.Request.Context(), sessionID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"session": h.serializeChatSession(session),
	})
}

// GetSessionWithMessages handles GET /api/chat/sessions/:id/messages
// Returns a session with all messages
func (h *ChatHandler) GetSessionWithMessages(c *gin.Context) {
	sessionID := c.Param("id")
	if sessionID == "" {
		h.handleError(c, errors.NewBadRequest("Session ID is required"))
		return
	}

	// Get session with messages
	result, err := h.chatUseCase.GetSessionWithMessages(c.Request.Context(), sessionID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	messages := make([]gin.H, len(result.Messages))
	for i, msg := range result.Messages {
		messages[i] = h.serializeChatMessage(msg)
	}

	c.JSON(http.StatusOK, gin.H{
		"session":  h.serializeChatSession(result.Session),
		"messages": messages,
	})
}

// SendMessage handles POST /api/chat/sessions/:id/messages
// Sends a message and gets LLM response (non-streaming)
func (h *ChatHandler) SendMessage(c *gin.Context) {
	sessionID := c.Param("id")
	if sessionID == "" {
		h.handleError(c, errors.NewBadRequest("Session ID is required"))
		return
	}

	// Parse request body
	var req struct {
		Message string `json:"message" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		h.handleError(c, errors.NewBadRequest("Message is required"))
		return
	}

	// Send message
	result, err := h.chatUseCase.SendMessage(c.Request.Context(), sessionID, req.Message)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"user_message":      h.serializeChatMessage(result.UserMessage),
		"assistant_message": h.serializeChatMessage(result.AssistantMessage),
		"tokens_used":       result.TokensUsed,
	})
}

// StreamMessage handles GET /api/chat/sessions/:id/stream
// Streams LLM response using Server-Sent Events (SSE)
func (h *ChatHandler) StreamMessage(c *gin.Context) {
	sessionID := c.Param("id")
	if sessionID == "" {
		h.handleError(c, errors.NewBadRequest("Session ID is required"))
		return
	}

	// Get message from query parameter
	message := c.Query("message")
	if message == "" {
		h.handleError(c, errors.NewBadRequest("Message query parameter is required"))
		return
	}

	// Set SSE headers
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	// Get channels from use case
	deltaChan, errorChan, err := h.chatUseCase.StreamMessage(c.Request.Context(), sessionID, message)
	if err != nil {
		h.handleError(c, err)
		return
	}

	// Get response writer flusher
	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		h.handleError(c, errors.NewInternal("Streaming not supported"))
		return
	}

	// Stream deltas
	h.log.Info("Starting SSE stream", logger.String("session_id", sessionID))

	for {
		select {
		case delta, ok := <-deltaChan:
			if !ok {
				// Stream finished successfully
				h.writeSSE(c.Writer, "done", gin.H{"status": "complete"})
				flusher.Flush()
				h.log.Info("SSE stream completed", logger.String("session_id", sessionID))
				return
			}

			// Send delta - extract content from choices
			var content string
			var finishReason *string
			if len(delta.Choices) > 0 {
				content = delta.Choices[0].Delta.Content
				finishReason = delta.Choices[0].FinishReason
			}

			h.writeSSE(c.Writer, "delta", gin.H{
				"content":       content,
				"finish_reason": finishReason,
			})
			flusher.Flush()

		case err := <-errorChan:
			// Error occurred
			h.log.Error("SSE stream error", logger.Error(err))
			h.writeSSE(c.Writer, "error", gin.H{
				"error": err.Error(),
			})
			flusher.Flush()
			return

		case <-c.Request.Context().Done():
			// Client disconnected
			h.log.Info("Client disconnected from SSE stream", logger.String("session_id", sessionID))
			return
		}
	}
}

// FinalizeSession handles POST /api/chat/sessions/:id/finalize
// Finalizes a session and extracts intent
func (h *ChatHandler) FinalizeSession(c *gin.Context) {
	sessionID := c.Param("id")
	if sessionID == "" {
		h.handleError(c, errors.NewBadRequest("Session ID is required"))
		return
	}

	// Finalize session
	intent, err := h.chatUseCase.FinalizeSession(c.Request.Context(), sessionID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"intent":  h.serializeIntent(intent),
		"message": "Session finalized and intent extracted",
	})
}

// GetUserSessions handles GET /api/chat/sessions
// Returns all sessions for the authenticated user
func (h *ChatHandler) GetUserSessions(c *gin.Context) {
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

	// Parse pagination parameters
	limit := h.getQueryInt(c, "limit", 20)
	offset := h.getQueryInt(c, "offset", 0)

	// Get user sessions
	sessions, err := h.chatUseCase.GetUserSessions(c.Request.Context(), user.ID, limit, offset)
	if err != nil {
		h.handleError(c, err)
		return
	}

	serialized := make([]gin.H, len(sessions))
	for i, session := range sessions {
		serialized[i] = h.serializeChatSession(session)
	}

	c.JSON(http.StatusOK, gin.H{
		"sessions": serialized,
		"count":    len(serialized),
	})
}

// GetActiveSessions handles GET /api/chat/sessions/active
// Returns active sessions for the authenticated user
func (h *ChatHandler) GetActiveSessions(c *gin.Context) {
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

	// Get active sessions
	sessions, err := h.chatUseCase.GetActiveSessions(c.Request.Context(), user.ID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	serialized := make([]gin.H, len(sessions))
	for i, session := range sessions {
		serialized[i] = h.serializeChatSession(session)
	}

	c.JSON(http.StatusOK, gin.H{
		"sessions": serialized,
		"count":    len(serialized),
	})
}

// CloseSession handles POST /api/chat/sessions/:id/close
// Manually closes a session without finalizing
func (h *ChatHandler) CloseSession(c *gin.Context) {
	sessionID := c.Param("id")
	if sessionID == "" {
		h.handleError(c, errors.NewBadRequest("Session ID is required"))
		return
	}

	// Close session
	err := h.chatUseCase.CloseSession(c.Request.Context(), sessionID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "Session closed successfully",
	})
}

// DeleteSession handles DELETE /api/chat/sessions/:id
// Deletes a session and its messages
func (h *ChatHandler) DeleteSession(c *gin.Context) {
	sessionID := c.Param("id")
	if sessionID == "" {
		h.handleError(c, errors.NewBadRequest("Session ID is required"))
		return
	}

	// Delete session
	err := h.chatUseCase.DeleteSession(c.Request.Context(), sessionID)
	if err != nil {
		h.handleError(c, err)
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "Session deleted successfully",
	})
}

// serializeChatSession converts a chat session entity to JSON response
func (h *ChatHandler) serializeChatSession(session *entity.ChatSession) gin.H {
	return gin.H{
		"id":                   session.ID,
		"user_id":              session.UserID,
		"project_id":           session.ProjectID,
		"status":               session.Status,
		"llm_model":            session.LLMModel,
		"token_usage":          session.TokenUsage,
		"max_tokens":           session.MaxTokens,
		"max_duration_minutes": session.MaxDurationMinutes,
		"created_at":           session.CreatedAt,
		"updated_at":           session.UpdatedAt,
	}
}

// serializeChatMessage converts a chat message entity to JSON response
func (h *ChatHandler) serializeChatMessage(message *entity.ChatMessage) gin.H {
	return gin.H{
		"id":         message.ID,
		"session_id": message.SessionID,
		"role":       message.Role,
		"content":    message.Content,
		"sequence":   message.Sequence,
		"tokens":     message.Tokens,
		"created_at": message.CreatedAt,
	}
}

// serializeIntent converts an intent entity to JSON response
func (h *ChatHandler) serializeIntent(intent *entity.Intent) gin.H {
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

// writeSSE writes a Server-Sent Event to the response writer
func (h *ChatHandler) writeSSE(w io.Writer, event string, data interface{}) {
	dataJSON, _ := json.Marshal(data)
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, dataJSON)
}

// getQueryInt extracts an integer query parameter with a default value
func (h *ChatHandler) getQueryInt(c *gin.Context, key string, defaultValue int) int {
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
func (h *ChatHandler) handleError(c *gin.Context, err error) {
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
