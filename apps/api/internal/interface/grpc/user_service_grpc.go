package grpc

import (
	"context"

	"github.com/zerozero/apps/api/internal/infrastructure/auth"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/logger"
	userv1 "github.com/zerozero/proto/gen/go/user/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// UserServiceGRPCServer implements the native gRPC UserService
type UserServiceGRPCServer struct {
	userv1.UnimplementedUserServiceServer
	userUseCase usecase.UserUseCase
	logger      logger.Logger
}

// NewUserServiceGRPCServer creates a new native gRPC user service server
func NewUserServiceGRPCServer(userUseCase usecase.UserUseCase, logger logger.Logger) *UserServiceGRPCServer {
	return &UserServiceGRPCServer{
		userUseCase: userUseCase,
		logger:      logger,
	}
}

// GetOrCreateMe implements the GetOrCreateMe RPC for native gRPC
func (s *UserServiceGRPCServer) GetOrCreateMe(
	ctx context.Context,
	req *userv1.GetOrCreateMeRequest,
) (*userv1.GetOrCreateMeResponse, error) {
	// Get auth user from context (set by auth interceptor)
	authUser, ok := ctx.Value("auth_user").(*auth.AuthUser)
	if !ok {
		return nil, status.Error(codes.Unauthenticated, "user not authenticated")
	}

	// Get or create user
	user, created, err := s.userUseCase.GetOrCreateUser(
		ctx,
		authUser.ClerkID,
		authUser.Email,
		authUser.FirstName,
		authUser.LastName,
		authUser.AvatarURL,
	)
	if err != nil {
		s.logger.Error("Failed to get or create user", logger.Error(err))
		return nil, s.handleError(err)
	}

	// Build response
	return &userv1.GetOrCreateMeResponse{
		User: &userv1.User{
			Id:        user.ID,
			ClerkId:   user.ClerkID,
			Email:     user.Email,
			FirstName: user.FirstName,
			LastName:  user.LastName,
			AvatarUrl: user.AvatarURL,
			CreatedAt: timestamppb.New(user.CreatedAt),
			UpdatedAt: timestamppb.New(user.UpdatedAt),
		},
		Created: created,
	}, nil
}

// UpdateProfile implements the UpdateProfile RPC for native gRPC
func (s *UserServiceGRPCServer) UpdateProfile(
	ctx context.Context,
	req *userv1.UpdateProfileRequest,
) (*userv1.UpdateProfileResponse, error) {
	// Get auth user from context
	authUser, ok := ctx.Value("auth_user").(*auth.AuthUser)
	if !ok {
		return nil, status.Error(codes.Unauthenticated, "user not authenticated")
	}

	// Update profile
	user, err := s.userUseCase.UpdateProfile(
		ctx,
		authUser.ClerkID,
		req.FirstName,
		req.LastName,
		req.AvatarUrl,
	)
	if err != nil {
		s.logger.Error("Failed to update profile", logger.Error(err))
		return nil, s.handleError(err)
	}

	// Build response
	return &userv1.UpdateProfileResponse{
		User: &userv1.User{
			Id:        user.ID,
			ClerkId:   user.ClerkID,
			Email:     user.Email,
			FirstName: user.FirstName,
			LastName:  user.LastName,
			AvatarUrl: user.AvatarURL,
			CreatedAt: timestamppb.New(user.CreatedAt),
			UpdatedAt: timestamppb.New(user.UpdatedAt),
		},
	}, nil
}

// handleError converts domain errors to gRPC errors
func (s *UserServiceGRPCServer) handleError(err error) error {
	if appErr, ok := err.(*errors.AppError); ok {
		switch appErr.Code {
		case errors.ErrNotFound:
			return status.Error(codes.NotFound, err.Error())
		case errors.ErrUnauthorized:
			return status.Error(codes.Unauthenticated, err.Error())
		case errors.ErrForbidden:
			return status.Error(codes.PermissionDenied, err.Error())
		case errors.ErrValidation, errors.ErrBadRequest:
			return status.Error(codes.InvalidArgument, err.Error())
		case errors.ErrConflict:
			return status.Error(codes.AlreadyExists, err.Error())
		case errors.ErrRateLimited:
			return status.Error(codes.ResourceExhausted, err.Error())
		case errors.ErrTimeout:
			return status.Error(codes.DeadlineExceeded, err.Error())
		case errors.ErrServiceUnavailable:
			return status.Error(codes.Unavailable, err.Error())
		default:
			return status.Error(codes.Internal, err.Error())
		}
	}

	return status.Error(codes.Internal, err.Error())
}
