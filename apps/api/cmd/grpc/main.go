package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joho/godotenv"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/infrastructure/db"
	grpchandler "github.com/zerozero/apps/api/internal/interface/grpc"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/config"
	"github.com/zerozero/apps/api/pkg/logger"

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
	// Load environment variables from root directory using absolute path
	rootDir := getRootDir()
	envPath := filepath.Join(rootDir, ".env.local")

	if err := godotenv.Load(envPath); err != nil {
		log.Printf("Warning: .env.local file not found at: %s", envPath)
	} else {
		log.Printf("Loaded environment from: %s", envPath)
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
	log.Info("Starting gRPC server", logger.String("environment", cfg.App.Environment))

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

	// Create gRPC server with interceptor
	grpcServer := grpc.NewServer(
		grpc.UnaryInterceptor(authUnaryInterceptor(clerkAuth, log)),
	)

	// Register services
	userService := grpchandler.NewUserServiceGRPCServer(userUseCase, log)
	userv1.RegisterUserServiceServer(grpcServer, userService)

	// Create listener
	lis, err := net.Listen("tcp", fmt.Sprintf(":%d", cfg.Server.GRPCPort))
	if err != nil {
		log.Fatal("Failed to create listener", logger.Error(err))
	}

	// Start server in goroutine
	go func() {
		log.Info("gRPC server started", logger.Int("port", cfg.Server.GRPCPort))
		if err := grpcServer.Serve(lis); err != nil {
			log.Fatal("Failed to serve gRPC", logger.Error(err))
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Info("Shutting down gRPC server...")
	grpcServer.GracefulStop()
	log.Info("gRPC server shutdown complete")
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
