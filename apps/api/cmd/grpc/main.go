package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/improbable-eng/grpc-web/go/grpcweb"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joho/godotenv"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	"github.com/zerozero/apps/api/internal/app"
	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/infrastructure/db"
	infraServices "github.com/zerozero/apps/api/internal/infrastructure/services"
	grpchandler "github.com/zerozero/apps/api/internal/interface/grpc"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/config"
	"github.com/zerozero/apps/api/pkg/logger"

	labsv1 "github.com/zerozero/proto/gen/go/labs/v1"
	testGrpc "github.com/zerozero/proto/gen/go/test"
	userv1 "github.com/zerozero/proto/gen/go/user/v1"
)

// getRootDir finds the git root directory
func getRootDir() string {
	dir, err := os.Getwd()
	if err != nil {
		return "."
	}

	// Walk up the directory tree to find git root
	for {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return dir
		}
		if _, err := os.Stat(filepath.Join(dir, "go.work")); err == nil {
			return dir
		}

		parent := filepath.Dir(dir)
		if parent == dir {
			// Reached filesystem root
			return "."
		}
		dir = parent
	}
}

func main() {
	// Load configuration (includes .env.local loading)
	cfg, err := app.LoadConfig()
	if err != nil {
		log.Fatalf("Failed to load configuration: %v", err)
	}

	// Initialize logger
	logLevel := "info"
	if cfg.App.Debug {
		logLevel = "debug"
	}
	appLogger := logger.New(logLevel)
	appLogger.Info("Starting gRPC server", logger.String("environment", cfg.App.Environment))

	// Connect to database
	dbPool, err := app.ConnectDatabase(cfg, appLogger)
	if err != nil {
		appLogger.Fatal("Failed to connect to database", logger.Error(err))
	}
	defer dbPool.Close()

	// Initialize Clerk auth
	// clerkAuth, err := auth.NewClerkAuth(cfg.Auth.ClerkSecretKey)
	// if err != nil {
	// 	log.Fatal("Failed to initialize Clerk auth", logger.Error(err))
	// }

	// Connect to database with GORM (needed for labs)
	gormDB, err := app.ConnectGORMDatabase(cfg, appLogger)
	if err != nil {
		appLogger.Fatal("Failed to connect to database with GORM", logger.Error(err))
	}

	// Initialize repositories
	userRepo := db.NewUserRepository(dbPool)
	labRepo := db.NewLabRepository(gormDB)

	// Initialize services
	blueprintService := infraServices.NewMockBlueprintService(appLogger)

	// Initialize use cases
	userUseCase := usecase.NewUserUseCase(userRepo, appLogger)
	labUseCase := usecase.NewLabUseCase(labRepo, userRepo, blueprintService, appLogger)

	// Create gRPC server with interceptor
	grpcServer := grpc.NewServer(
	// grpc.UnaryInterceptor(authUnaryInterceptor(clerkAuth, log)),
	)

	// Register services
	userService := grpchandler.NewUserServiceGRPCServer(userUseCase, appLogger)
	userv1.RegisterUserServiceServer(grpcServer, userService)

	testUseCase := usecase.NewTestUseCase(appLogger)
	testService := grpchandler.NewTestServiceGRPCServer(testUseCase)
	testGrpc.RegisterTestServiceServer(grpcServer, testService)

	// Register Labs service (for Temporal activities)
	labsService := grpchandler.NewLabsServiceGRPCServer(labUseCase, labRepo, blueprintService, appLogger)
	labsv1.RegisterLabsServiceServer(grpcServer, labsService)

	// Wrap gRPC server with grpc-web
	wrappedGrpc := grpcweb.WrapServer(grpcServer,
		grpcweb.WithCorsForRegisteredEndpointsOnly(false),
		grpcweb.WithOriginFunc(func(origin string) bool {
			// Allow all origins for development
			return true
		}),
	)

	// Create HTTP server that handles both gRPC and gRPC-Web
	httpServer := &http.Server{
		Addr: fmt.Sprintf(":%d", cfg.Server.GRPCPort),
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if wrappedGrpc.IsGrpcWebRequest(r) {
				wrappedGrpc.ServeHTTP(w, r)
			} else {
				// Fall back to standard gRPC
				grpcServer.ServeHTTP(w, r)
			}
		}),
	}

	// Start server in goroutine
	go func() {
		appLogger.Info("gRPC server with gRPC-Web started", logger.Int("port", cfg.Server.GRPCPort))
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			appLogger.Fatal("Failed to serve gRPC", logger.Error(err))
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	appLogger.Info("Shutting down gRPC server...")
	if err := httpServer.Shutdown(context.Background()); err != nil {
		appLogger.Error("Error shutting down HTTP server", logger.Error(err))
	}
	grpcServer.GracefulStop()
	appLogger.Info("gRPC server shutdown complete")
}

// authUnaryInterceptor is a gRPC interceptor for authentication
func authUnaryInterceptor(clerkAuth *auth.ClerkAuth, log logger.Logger) grpc.UnaryServerInterceptor {
	return func(
		ctx context.Context,
		req interface{},
		info *grpc.UnaryServerInfo,
		handler grpc.UnaryHandler,
	) (interface{}, error) {
		// Get metadata from context
		md, ok := metadata.FromIncomingContext(ctx)
		if !ok {
			return nil, fmt.Errorf("missing metadata")
		}

		// Get authorization header
		authHeaders := md.Get("authorization")
		if len(authHeaders) == 0 {
			return nil, fmt.Errorf("authorization header required")
		}

		authHeader := authHeaders[0]
		token := strings.TrimPrefix(authHeader, "Bearer ")

		// Verify token
		authUser, err := clerkAuth.VerifyToken(token)
		if err != nil {
			log.Error("Failed to verify token", logger.Error(err))
			return nil, fmt.Errorf("invalid token")
		}

		// Add auth user to context
		ctx = context.WithValue(ctx, "auth_user", authUser)
		ctx = context.WithValue(ctx, "clerk_id", authUser.ClerkID)

		return handler(ctx, req)
	}
}
