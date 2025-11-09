package http

import (
    "net/http"
    "github.com/gin-gonic/gin"
    "github.com/zerozero/apps/api/internal/infrastructure/auth"
    "github.com/zerozero/apps/api/internal/usecase"
    "github.com/zerozero/apps/api/pkg/errors"
    "github.com/zerozero/apps/api/pkg/logger"
)

// UserHandler handles HTTP requests for users
type UserHandler struct {
    userUseCase usecase.UserUseCase
    clerkAuth   *auth.ClerkAuth
    logger      logger.Logger
}

// NewUserHandler creates a new user handler
func NewUserHandler(userUseCase usecase.UserUseCase, clerkAuth *auth.ClerkAuth, logger logger.Logger) *UserHandler {
    return &UserHandler{
        userUseCase: userUseCase,
        clerkAuth:   clerkAuth,
        logger:      logger,
    }
}

// GetMe handles GET /api/me - gets or creates the authenticated user
func (h *UserHandler) GetMe(c *gin.Context) {
    // Get authenticated user from context
    authUser, err := auth.GetAuthUser(c)
    if err != nil {
        h.handleError(c, err)
        return
    }

    // If email is missing from JWT claims, fetch full user data from Clerk API
    if authUser.Email == "" {
        h.logger.Debug("Email missing from JWT, fetching from Clerk API",
            logger.String("clerk_id", authUser.ClerkID),
        )
        fullUser, err := h.clerkAuth.GetUser(c.Request.Context(), authUser.ClerkID)
        if err != nil {
            h.logger.Error("Failed to fetch user from Clerk API",
                logger.Error(err),
                logger.String("clerk_id", authUser.ClerkID),
            )
            h.handleError(c, errors.NewInternal("Failed to fetch user details"))
            return
        }
        authUser = fullUser
    }

    // Get or create user
    user, created, err := h.userUseCase.GetOrCreateUser(
        c.Request.Context(),
        authUser.ClerkID,
        authUser.Email,
        authUser.FirstName,
        authUser.LastName,
        authUser.AvatarURL,
    )
    if err != nil {
        h.handleError(c, err)
        return
    }

    // Return response
    c.JSON(http.StatusOK, gin.H{
        "user": gin.H{
            "id":         user.ID,
            "clerk_id":   user.ClerkID,
            "email":      user.Email,
            "first_name": user.FirstName,
            "last_name":  user.LastName,
            "avatar_url": user.AvatarURL,
            "created_at": user.CreatedAt,
            "updated_at": user.UpdatedAt,
        },
        "created": created,
    })
}

// UpdateProfile handles PATCH /api/me - updates the authenticated user's profile
func (h *UserHandler) UpdateProfile(c *gin.Context) {
    // Get authenticated user from context
    clerkID, err := auth.GetClerkID(c)
    if err != nil {
        h.handleError(c, err)
        return
    }

    // Parse request body
    var req struct {
        FirstName string `json:"first_name"`
        LastName  string `json:"last_name"`
        AvatarURL string `json:"avatar_url"`
    }
    if err := c.ShouldBindJSON(&req); err != nil {
        h.handleError(c, errors.NewBadRequest("Invalid request body"))
        return
    }

    // Update profile
    user, err := h.userUseCase.UpdateProfile(
        c.Request.Context(),
        clerkID,
        req.FirstName,
        req.LastName,
        req.AvatarURL,
    )
    if err != nil {
        h.handleError(c, err)
        return
    }

    // Return response
    c.JSON(http.StatusOK, gin.H{
        "user": gin.H{
            "id":         user.ID,
            "clerk_id":   user.ClerkID,
            "email":      user.Email,
            "first_name": user.FirstName,
            "last_name":  user.LastName,
            "avatar_url": user.AvatarURL,
            "created_at": user.CreatedAt,
            "updated_at": user.UpdatedAt,
        },
    })
}

// handleError handles errors and returns appropriate HTTP responses
func (h *UserHandler) handleError(c *gin.Context, err error) {
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
    h.logger.Error("Unhandled error", logger.Error(err))
    c.JSON(http.StatusInternalServerError, gin.H{
        "error": gin.H{
            "code":    "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
        },
    })
}