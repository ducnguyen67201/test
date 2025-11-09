package grpc

import (
	"context"

	"github.com/zerozero/apps/api/internal/usecase"
	test "github.com/zerozero/proto/gen/go/test"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type TestServiceGRPCServer struct {
	test.UnimplementedTestServiceServer
	testUseCase usecase.TestUseCase
}

func NewTestServiceGRPCServer(testUseCase usecase.TestUseCase) *TestServiceGRPCServer {
	return &TestServiceGRPCServer{
		testUseCase: testUseCase,
	}
}

func (s *TestServiceGRPCServer) GetTestMessage(
	ctx context.Context,
	req *test.GetTestMessageRequest,
) (*test.GetTestMessageResponse, error) {
	message, err := s.testUseCase.GetTestMessage(ctx)
	if err != nil {
		return nil, err
	}

	return &test.GetTestMessageResponse{
		Message: &test.TestMessage{
			Id:        "test-id",
			Name:      message,
			CreatedAt: timestamppb.Now(),
		},
	}, nil
}
