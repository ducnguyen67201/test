package auth

import (
    "context"
    "fmt"
    "strings"
    "github.com/clerk/clerk-sdk-go/v2"
    clerkjwt "github.com/clerk/clerk-sdk-go/v2/jwt"
    "github.com/gin-gonic/gin"
    "github.com/zerozero/apps/api/pkg/errors"
)

// ClerkAuth handles Clerk authentication
type ClerkAuth struct {
    client    *clerk.Client
    secretKey string
}

// NewClerkAuth creates a new Clerk auth handler
func NewClerkAuth(secretKey string) (*ClerkAuth, error) {
    if secretKey == "" {
        return nil, fmt.Errorf("clerk secret key is required")
    }

    client, err := clerk.NewClient(secretKey)
    if err != nil {
        return nil, fmt.Errorf("failed to create clerk client: %w", err)
    }

    return &ClerkAuth{
        client:    client,
        secretKey: secretKey,
    }, nil
}

// AuthUser represents an authenticated user
type AuthUser struct {
    ClerkID   string
    Email     string
    FirstName string
    LastName  string
    AvatarURL string
}

// VerifyToken verifies a JWT token from Clerk
func (ca *ClerkAuth) VerifyToken(tokenString string) (*AuthUser, error) {
    // Remove Bearer prefix if present
    tokenString = strings.TrimPrefix(tokenString, "Bearer ")
    tokenString = strings.TrimSpace(tokenString)

    // Verify the token
    claims, err := clerkjwt.Verify(context.Background(), &clerkjwt.VerifyParams{
        Token: tokenString,
        JWK:   nil, // Will use the default Clerk JWK
    })
    if err != nil {
        return nil, fmt.Errorf("failed to verify token: %w", err)
    }

    // Extract user information from claims
    authUser := &AuthUser{
        ClerkID: claims.Subject,
    }

    // Get additional user info if available
    if email, ok := claims.Extra["email"].(string); ok {
        authUser.Email = email
    }
    if firstName, ok := claims.Extra["first_name"].(string); ok {
        authUser.FirstName = firstName
    }
    if lastName, ok := claims.Extra["last_name"].(string); ok {
        authUser.LastName = lastName
    }
    if avatarURL, ok := claims.Extra["image_url"].(string); ok {
        authUser.AvatarURL = avatarURL
    }

    return authUser, nil
}

// GetUser gets a user from Clerk by ID
func (ca *ClerkAuth) GetUser(ctx context.Context, clerkID string) (*AuthUser, error) {
    user, err := ca.client.Users().Read(ctx, clerkID)
    if err != nil {
        return nil, fmt.Errorf("failed to get user from clerk: %w", err)
    }

    authUser := &AuthUser{
        ClerkID:   user.ID,
        FirstName: *user.FirstName,
        LastName:  *user.LastName,
    }

    // Get primary email
    if user.PrimaryEmailAddressID != nil && len(user.EmailAddresses) > 0 {
        for _, email := range user.EmailAddresses {
            if email.ID == *user.PrimaryEmailAddressID {
                authUser.Email = email.EmailAddress
                break
            }
        }
    }

    // Get profile image
    if user.ProfileImageURL != nil {
        authUser.AvatarURL = *user.ProfileImageURL
    }

    return authUser, nil
}

// Middleware creates a Gin middleware for authentication
func (ca *ClerkAuth) Middleware() gin.HandlerFunc {
    return func(c *gin.Context) {
        // Get token from Authorization header
        authHeader := c.GetHeader("Authorization")
        if authHeader == "" {
            c.JSON(401, gin.H{"error": "Authorization header required"})
            c.Abort()
            return
        }

        // Verify token
        authUser, err := ca.VerifyToken(authHeader)
        if err != nil {
            c.JSON(401, gin.H{"error": "Invalid token"})
            c.Abort()
            return
        }

        // Set user in context
        c.Set("auth_user", authUser)
        c.Set("clerk_id", authUser.ClerkID)
        c.Next()
    }
}

// GetAuthUser gets the authenticated user from Gin context
func GetAuthUser(c *gin.Context) (*AuthUser, error) {
    value, exists := c.Get("auth_user")
    if !exists {
        return nil, errors.NewUnauthorized("User not authenticated")
    }

    authUser, ok := value.(*AuthUser)
    if !ok {
        return nil, errors.NewInternal("Invalid auth user in context")
    }

    return authUser, nil
}

// GetClerkID gets the Clerk ID from Gin context
func GetClerkID(c *gin.Context) (string, error) {
    value, exists := c.Get("clerk_id")
    if !exists {
        return "", errors.NewUnauthorized("User not authenticated")
    }

    clerkID, ok := value.(string)
    if !ok {
        return "", errors.NewInternal("Invalid clerk ID in context")
    }

    return clerkID, nil
}