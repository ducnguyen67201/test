package grpc

import (
    "context"
    "connectrpc.com/connect"
    "github.com/zerozero/apps/api/internal/infrastructure/auth"
    "github.com/zerozero/apps/api/internal/usecase"
    "github.com/zerozero/apps/api/pkg/errors"
    "github.com/zerozero/apps/api/pkg/logger"
    userv1 "github.com/zerozero/proto/gen/go/user/v1"
    "google.golang.org/protobuf/types/known/timestamppb"
)

// UserServiceServer implements the UserService gRPC service
type UserServiceServer struct {
    userUseCase usecase.UserUseCase
    logger      logger.Logger
}

// NewUserServiceServer creates a new user service server
func NewUserServiceServer(userUseCase usecase.UserUseCase, logger logger.Logger) *UserServiceServer {
    return &UserServiceServer{
        userUseCase: userUseCase,
        logger:      logger,
    }
}

// GetOrCreateMe implements the GetOrCreateMe RPC
func (s *UserServiceServer) GetOrCreateMe(
    ctx context.Context,
    req *connect.Request[userv1.GetOrCreateMeRequest],
) (*connect.Response[userv1.GetOrCreateMeResponse], error) {
    // Get auth user from context (set by auth interceptor)
    authUser, ok := ctx.Value("auth_user").(*auth.AuthUser)
    if !ok {
        return nil, connect.NewError(connect.CodeUnauthenticated, errors.NewUnauthorized("User not authenticated"))
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
    res := connect.NewResponse(&userv1.GetOrCreateMeResponse{
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
    })

    return res, nil
}

// UpdateProfile implements the UpdateProfile RPC
func (s *UserServiceServer) UpdateProfile(
    ctx context.Context,
    req *connect.Request[userv1.UpdateProfileRequest],
) (*connect.Response[userv1.UpdateProfileResponse], error) {
    // Get auth user from context
    authUser, ok := ctx.Value("auth_user").(*auth.AuthUser)
    if !ok {
        return nil, connect.NewError(connect.CodeUnauthenticated, errors.NewUnauthorized("User not authenticated"))
    }

    // Update profile
    user, err := s.userUseCase.UpdateProfile(
        ctx,
        authUser.ClerkID,
        req.Msg.FirstName,
        req.Msg.LastName,
        req.Msg.AvatarUrl,
    )
    if err != nil {
        s.logger.Error("Failed to update profile", logger.Error(err))
        return nil, s.handleError(err)
    }

    // Build response
    res := connect.NewResponse(&userv1.UpdateProfileResponse{
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
    })

    return res, nil
}

// handleError converts domain errors to gRPC errors
func (s *UserServiceServer) handleError(err error) error {
    if appErr, ok := err.(*errors.AppError); ok {
        switch appErr.Code {
        case errors.ErrNotFound:
            return connect.NewError(connect.CodeNotFound, err)
        case errors.ErrUnauthorized:
            return connect.NewError(connect.CodeUnauthenticated, err)
        case errors.ErrForbidden:
            return connect.NewError(connect.CodePermissionDenied, err)
        case errors.ErrValidation, errors.ErrBadRequest:
            return connect.NewError(connect.CodeInvalidArgument, err)
        case errors.ErrConflict:
            return connect.NewError(connect.CodeAlreadyExists, err)
        case errors.ErrRateLimited:
            return connect.NewError(connect.CodeResourceExhausted, err)
        case errors.ErrTimeout:
            return connect.NewError(connect.CodeDeadlineExceeded, err)
        case errors.ErrServiceUnavailable:
            return connect.NewError(connect.CodeUnavailable, err)
        default:
            return connect.NewError(connect.CodeInternal, err)
        }
    }

    return connect.NewError(connect.CodeInternal, err)
}