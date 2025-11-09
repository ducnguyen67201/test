package middleware

import (
	"context"
	"fmt"
	"strings"

	"connectrpc.com/connect"
	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/pkg/logger"
)

// AuthInterceptor is a Connect interceptor for authentication
type AuthInterceptor struct {
	clerkAuth *auth.ClerkAuth
	logger    logger.Logger
}

// NewAuthInterceptor creates a new auth interceptor
func NewAuthInterceptor(clerkAuth *auth.ClerkAuth, logger logger.Logger) *AuthInterceptor {
	return &AuthInterceptor{
		clerkAuth: clerkAuth,
		logger:    logger,
	}
}

// WrapUnary implements connect.Interceptor
func (i *AuthInterceptor) WrapUnary(next connect.UnaryFunc) connect.UnaryFunc {
	return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		// Get authorization header
		authHeader := req.Header().Get("Authorization")
		if authHeader == "" {
			return nil, connect.NewError(connect.CodeUnauthenticated, fmt.Errorf("authorization header required"))
		}

		// Verify token
		authUser, err := i.clerkAuth.VerifyToken(strings.TrimPrefix(authHeader, "Bearer "))
		if err != nil {
			i.logger.Error("Failed to verify token", logger.Error(err))
			return nil, connect.NewError(connect.CodeUnauthenticated, fmt.Errorf("invalid token"))
		}

		// Add auth user to context
		ctx = context.WithValue(ctx, "auth_user", authUser)
		ctx = context.WithValue(ctx, "clerk_id", authUser.ClerkID)

		return next(ctx, req)
	}
}

// WrapStreamingClient implements connect.Interceptor
func (i *AuthInterceptor) WrapStreamingClient(next connect.StreamingClientFunc) connect.StreamingClientFunc {
	return next
}

// WrapStreamingHandler implements connect.Interceptor
func (i *AuthInterceptor) WrapStreamingHandler(next connect.StreamingHandlerFunc) connect.StreamingHandlerFunc {
	return next
}
