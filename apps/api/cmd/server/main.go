package main

import (
    "context"
    "fmt"
    "log"
    "net/http"
    "os"
    "os/signal"
    "strings"
    "syscall"
    "time"

    "connectrpc.com/connect"
    "github.com/gin-gonic/gin"
    "github.com/jackc/pgx/v5/pgxpool"
    "github.com/joho/godotenv"

    "github.com/zerozero/apps/api/internal/infrastructure/auth"
    "github.com/zerozero/apps/api/internal/infrastructure/db"
    grpchandler "github.com/zerozero/apps/api/internal/interface/grpc"
    httphandler "github.com/zerozero/apps/api/internal/interface/http"
    "github.com/zerozero/apps/api/internal/usecase"
    "github.com/zerozero/apps/api/pkg/config"
    "github.com/zerozero/apps/api/pkg/logger"

    userv1connect "github.com/zerozero/proto/gen/go/user/v1/v1connect"
)

func main() {
    // Load environment variables
    if err := godotenv.Load(".env.local"); err != nil {
        log.Printf("Warning: .env.local file not found: %v", err)
    }

    // Load configuration
    cfg, err := config.Load()
    if err != nil {
        log.Fatalf("Failed to load configuration: %v", err)
    }

    // Initialize logger
    logLevel := "info"
    if cfg.App.Debug {
        logLevel = "debug"
    }
    log := logger.New(logLevel)
    log.Info("Starting server", logger.String("environment", cfg.App.Environment))

    // Connect to database
    dbPool, err := pgxpool.New(context.Background(), cfg.Database.URL)
    if err != nil {
        log.Fatal("Failed to connect to database", logger.Error(err))
    }
    defer dbPool.Close()

    // Ping database
    if err := dbPool.Ping(context.Background()); err != nil {
        log.Fatal("Failed to ping database", logger.Error(err))
    }
    log.Info("Connected to database")

    // Initialize Clerk auth
    clerkAuth, err := auth.NewClerkAuth(cfg.Auth.ClerkSecretKey)
    if err != nil {
        log.Fatal("Failed to initialize Clerk auth", logger.Error(err))
    }

    // Initialize repositories
    userRepo := db.NewUserRepository(dbPool)

    // Initialize use cases
    userUseCase := usecase.NewUserUseCase(userRepo, log)

    // Initialize Gin
    if !cfg.App.Debug {
        gin.SetMode(gin.ReleaseMode)
    }
    router := gin.New()
    router.Use(gin.Recovery())
    router.Use(corsMiddleware(cfg.Server.CorsOrigins))
    router.Use(loggingMiddleware(log))

    // Health check endpoint (no auth required)
    router.GET("/health", func(c *gin.Context) {
        c.JSON(http.StatusOK, gin.H{
            "status": "healthy",
            "time":   time.Now(),
        })
    })

    // API routes with authentication
    api := router.Group("/api")
    api.Use(clerkAuth.Middleware())
    {
        userHandler := httphandler.NewUserHandler(userUseCase, log)
        api.GET("/me", userHandler.GetMe)
        api.PATCH("/me", userHandler.UpdateProfile)
    }

    // gRPC/Connect routes
    grpcUserService := grpchandler.NewUserServiceServer(userUseCase, log)
    path, handler := userv1connect.NewUserServiceHandler(
        grpcUserService,
        connect.WithInterceptors(
            NewAuthInterceptor(clerkAuth, log),
        ),
    )

    // Mount Connect handler
    router.Any(path+"*path", gin.WrapH(handler))

    // Start server
    srv := &http.Server{
        Addr:         fmt.Sprintf(":%d", cfg.Server.Port),
        Handler:      router,
        ReadTimeout:  time.Duration(cfg.Server.ReadTimeout) * time.Second,
        WriteTimeout: time.Duration(cfg.Server.WriteTimeout) * time.Second,
    }

    // Graceful shutdown
    go func() {
        log.Info("Server started", logger.Int("port", cfg.Server.Port))
        if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            log.Fatal("Failed to start server", logger.Error(err))
        }
    }()

    // Wait for interrupt signal
    quit := make(chan os.Signal, 1)
    signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
    <-quit

    log.Info("Shutting down server...")
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()

    if err := srv.Shutdown(ctx); err != nil {
        log.Fatal("Server forced to shutdown", logger.Error(err))
    }

    log.Info("Server shutdown complete")
}

// corsMiddleware handles CORS
func corsMiddleware(allowedOrigins []string) gin.HandlerFunc {
    return func(c *gin.Context) {
        origin := c.Request.Header.Get("Origin")

        // Check if origin is allowed
        for _, allowed := range allowedOrigins {
            if origin == allowed {
                c.Writer.Header().Set("Access-Control-Allow-Origin", origin)
                break
            }
        }

        c.Writer.Header().Set("Access-Control-Allow-Credentials", "true")
        c.Writer.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        c.Writer.Header().Set("Access-Control-Allow-Headers", "Accept, Authorization, Content-Type, Content-Length, Accept-Encoding, Connect-Protocol-Version")

        if c.Request.Method == "OPTIONS" {
            c.AbortWithStatus(http.StatusNoContent)
            return
        }

        c.Next()
    }
}

// loggingMiddleware logs requests
func loggingMiddleware(log logger.Logger) gin.HandlerFunc {
    return func(c *gin.Context) {
        start := time.Now()
        path := c.Request.URL.Path
        raw := c.Request.URL.RawQuery

        // Process request
        c.Next()

        // Skip health check logging
        if path == "/health" {
            return
        }

        latency := time.Since(start)
        if raw != "" {
            path = path + "?" + raw
        }

        log.Info("Request processed",
            logger.String("method", c.Request.Method),
            logger.String("path", path),
            logger.Int("status", c.Writer.Status()),
            logger.String("latency", latency.String()),
            logger.String("ip", c.ClientIP()),
        )
    }
}

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