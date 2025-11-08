package auth

import (
    "context"
    "fmt"
    "strings"
    "github.com/clerk/clerk-sdk-go/v2"
    clerkjwt "github.com/clerk/clerk-sdk-go/v2/jwt"
    "github.com/clerk/clerk-sdk-go/v2/user"
    "github.com/gin-gonic/gin"
    "github.com/zerozero/apps/api/pkg/errors"
)

// ClerkAuth handles Clerk authentication
type ClerkAuth struct {
    secretKey string
}

// NewClerkAuth creates a new Clerk auth handler
func NewClerkAuth(secretKey string) (*ClerkAuth, error) {
    if secretKey == "" {
        return nil, fmt.Errorf("clerk secret key is required")
    }

    // Set the global Clerk API key
    clerk.SetKey(secretKey)

    return &ClerkAuth{
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

    // Get additional user info from custom claims if available
    if customMap, ok := claims.Custom.(map[string]interface{}); ok {
        if email, ok := customMap["email"].(string); ok {
            authUser.Email = email
        }
        if firstName, ok := customMap["first_name"].(string); ok {
            authUser.FirstName = firstName
        }
        if lastName, ok := customMap["last_name"].(string); ok {
            authUser.LastName = lastName
        }
        if avatarURL, ok := customMap["image_url"].(string); ok {
            authUser.AvatarURL = avatarURL
        }
    }

    return authUser, nil
}

// GetUser gets a user from Clerk by ID
func (ca *ClerkAuth) GetUser(ctx context.Context, clerkID string) (*AuthUser, error) {
    userObj, err := user.Get(ctx, clerkID)
    if err != nil {
        return nil, fmt.Errorf("failed to get user from clerk: %w", err)
    }

    authUser := &AuthUser{
        ClerkID: userObj.ID,
    }

    // Set names if available
    if userObj.FirstName != nil {
        authUser.FirstName = *userObj.FirstName
    }
    if userObj.LastName != nil {
        authUser.LastName = *userObj.LastName
    }

    // Get primary email
    if userObj.PrimaryEmailAddressID != nil && len(userObj.EmailAddresses) > 0 {
        for _, email := range userObj.EmailAddresses {
            if email.ID == *userObj.PrimaryEmailAddressID {
                authUser.Email = email.EmailAddress
                break
            }
        }
    }

    // Get profile image
    if userObj.ProfileImageURL != nil {
        authUser.AvatarURL = *userObj.ProfileImageURL
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