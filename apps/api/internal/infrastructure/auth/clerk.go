package auth

import (
    "context"
    "fmt"
    "strings"
    "sync"
    "time"

    "github.com/clerk/clerk-sdk-go/v2"
    "github.com/clerk/clerk-sdk-go/v2/user"
    "github.com/gin-gonic/gin"
    "github.com/golang-jwt/jwt/v5"
    "github.com/lestrrat-go/jwx/v2/jwk"
    "github.com/zerozero/apps/api/pkg/errors"
    "github.com/zerozero/apps/api/pkg/logger"
)

const (
    // JWKCacheDuration is how long to cache JWKs before refetching
    JWKCacheDuration = 1 * time.Hour
    // JWKFetchTimeout is the timeout for fetching JWKs
    JWKFetchTimeout = 10 * time.Second
)

// ClerkAuth handles Clerk authentication with JWT token verification
type ClerkAuth struct {
    jwksURL   string
    jwkSet    jwk.Set
    jwkMutex  sync.RWMutex
    lastFetch time.Time
    log       logger.Logger
}

// NewClerkAuth creates a new Clerk auth handler
func NewClerkAuth(secretKey string, jwksURL string, log logger.Logger) (*ClerkAuth, error) {
    if secretKey == "" {
        return nil, fmt.Errorf("clerk secret key is required")
    }
    if jwksURL == "" {
        return nil, fmt.Errorf("clerk JWKS URL is required")
    }

    // Set the global Clerk API key for SDK operations
    clerk.SetKey(secretKey)

    return &ClerkAuth{
        jwksURL: jwksURL,
        log:     log,
    }, nil
}

// AuthUser represents an authenticated user from Clerk
type AuthUser struct {
    ClerkID   string
    Email     string
    FirstName string
    LastName  string
    AvatarURL string
}

// fetchJWKS fetches the JSON Web Key Set from Clerk's JWKS endpoint
func (ca *ClerkAuth) fetchJWKS() (jwk.Set, error) {
    ctx, cancel := context.WithTimeout(context.Background(), JWKFetchTimeout)
    defer cancel()

    set, err := jwk.Fetch(ctx, ca.jwksURL)
    if err != nil {
        return nil, fmt.Errorf("failed to fetch JWKS from %s: %w", ca.jwksURL, err)
    }

    return set, nil
}

// getJWKSet retrieves the JWK set, fetching from Clerk if cache is stale
func (ca *ClerkAuth) getJWKSet() (jwk.Set, error) {
    // Fast path: check if cache is fresh
    ca.jwkMutex.RLock()
    if ca.jwkSet != nil && time.Since(ca.lastFetch) <= JWKCacheDuration {
        defer ca.jwkMutex.RUnlock()
        return ca.jwkSet, nil
    }
    ca.jwkMutex.RUnlock()

    // Slow path: fetch new keys
    ca.jwkMutex.Lock()
    defer ca.jwkMutex.Unlock()

    // Double-check after acquiring write lock
    if ca.jwkSet != nil && time.Since(ca.lastFetch) <= JWKCacheDuration {
        return ca.jwkSet, nil
    }

    set, err := ca.fetchJWKS()
    if err != nil {
        return nil, err
    }

    ca.jwkSet = set
    ca.lastFetch = time.Now()
    ca.log.Debug("JWK set refreshed from Clerk")

    return ca.jwkSet, nil
}

// VerifyToken verifies a Clerk JWT token and extracts user information
func (ca *ClerkAuth) VerifyToken(tokenString string) (*AuthUser, error) {
    // Clean up token string
    tokenString = strings.TrimPrefix(tokenString, "Bearer ")
    tokenString = strings.TrimSpace(tokenString)

    // Parse token header to get the key ID (kid)
    token, _, err := jwt.NewParser().ParseUnverified(tokenString, jwt.MapClaims{})
    if err != nil {
        return nil, fmt.Errorf("failed to parse token: %w", err)
    }

    kid, ok := token.Header["kid"].(string)
    if !ok {
        return nil, fmt.Errorf("token missing 'kid' in header")
    }

    // Get the JWK set (cached or fetched)
    keySet, err := ca.getJWKSet()
    if err != nil {
        return nil, fmt.Errorf("failed to get JWK set: %w", err)
    }

    // Find the specific key by ID
    key, found := keySet.LookupKeyID(kid)
    if !found {
        return nil, fmt.Errorf("JWK with kid '%s' not found", kid)
    }

    // Extract the raw public key
    var publicKey interface{}
    if err := key.Raw(&publicKey); err != nil {
        return nil, fmt.Errorf("failed to extract public key: %w", err)
    }

    // Verify the token signature
    token, err = jwt.Parse(tokenString, func(t *jwt.Token) (interface{}, error) {
        return publicKey, nil
    })
    if err != nil {
        return nil, fmt.Errorf("token verification failed: %w", err)
    }

    if !token.Valid {
        return nil, fmt.Errorf("token is invalid")
    }

    // Extract claims
    claims, ok := token.Claims.(jwt.MapClaims)
    if !ok {
        return nil, fmt.Errorf("invalid token claims format")
    }

    // Build AuthUser from claims
    authUser := &AuthUser{}

    if sub, ok := claims["sub"].(string); ok {
        authUser.ClerkID = sub
    } else {
        return nil, fmt.Errorf("token missing 'sub' claim")
    }

    // Optional claims
    if email, ok := claims["email"].(string); ok {
        authUser.Email = email
    }
    if firstName, ok := claims["first_name"].(string); ok {
        authUser.FirstName = firstName
    }
    if lastName, ok := claims["last_name"].(string); ok {
        authUser.LastName = lastName
    }
    if imageURL, ok := claims["image_url"].(string); ok {
        authUser.AvatarURL = imageURL
    }

    return authUser, nil
}

// GetUser fetches user details from Clerk by ID
func (ca *ClerkAuth) GetUser(ctx context.Context, clerkID string) (*AuthUser, error) {
    userObj, err := user.Get(ctx, clerkID)
    if err != nil {
        return nil, fmt.Errorf("failed to get user from Clerk: %w", err)
    }

    authUser := &AuthUser{
        ClerkID: userObj.ID,
    }

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

    if userObj.ImageURL != nil {
        authUser.AvatarURL = *userObj.ImageURL
    }

    return authUser, nil
}

// Middleware creates a Gin middleware for JWT authentication
func (ca *ClerkAuth) Middleware() gin.HandlerFunc {
    return func(c *gin.Context) {
        authHeader := c.GetHeader("Authorization")
        if authHeader == "" {
            ca.log.Warn("Request missing Authorization header")
            c.JSON(401, gin.H{"error": "Authorization header required"})
            c.Abort()
            return
        }

        authUser, err := ca.VerifyToken(authHeader)
        if err != nil {
            ca.log.Error("Token verification failed",
                logger.Error(err),
                logger.String("ip", c.ClientIP()),
            )
            c.JSON(401, gin.H{"error": "Invalid token"})
            c.Abort()
            return
        }

        ca.log.Debug("User authenticated",
            logger.String("clerk_id", authUser.ClerkID),
            logger.String("email", authUser.Email),
        )

        // Set user in context for downstream handlers
        c.Set("auth_user", authUser)
        c.Set("clerk_id", authUser.ClerkID)
        c.Next()
    }
}

// GetAuthUser retrieves the authenticated user from Gin context
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

// GetClerkID retrieves the Clerk user ID from Gin context
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
