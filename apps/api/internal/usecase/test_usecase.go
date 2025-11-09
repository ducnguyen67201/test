package usecase

import (
	"context"

	"github.com/zerozero/apps/api/pkg/logger"
)

type TestUseCase interface {
	GetTestMessage(ctx context.Context) (string, error)
}

type NOPtestUseCase struct {
	logger logger.Logger
}

func NewTestUseCase(logger logger.Logger) TestUseCase {
	return &NOPtestUseCase{
		logger: logger,
	}
}

func (uc *NOPtestUseCase) GetTestMessage(ctx context.Context) (string, error) {
	return "Test message from TestUseCase", nil
}
