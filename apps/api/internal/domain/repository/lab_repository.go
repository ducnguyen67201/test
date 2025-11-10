package repository

import (
	"context"
	"github.com/zerozero/apps/api/internal/domain/entity"
)

// LabRepository defines the interface for lab request data access
type LabRepository interface {
	// GetByID retrieves a lab request by its ID
	GetByID(ctx context.Context, id string) (*entity.LabRequest, error)

	// GetByUserID retrieves all lab requests for a specific user
	GetByUserID(ctx context.Context, userID string, limit, offset int) ([]*entity.LabRequest, error)

	// GetActiveByUserID retrieves active (queued or running) labs for a user
	GetActiveByUserID(ctx context.Context, userID string) ([]*entity.LabRequest, error)

	// CountActiveByUserID counts active labs for a specific user
	CountActiveByUserID(ctx context.Context, userID string) (int64, error)

	// Create creates a new lab request
	Create(ctx context.Context, labRequest *entity.LabRequest) (*entity.LabRequest, error)

	// Update updates an existing lab request
	Update(ctx context.Context, labRequest *entity.LabRequest) (*entity.LabRequest, error)

	// Delete deletes a lab request
	Delete(ctx context.Context, id string) error

	// List lists lab requests with pagination
	List(ctx context.Context, limit, offset int) ([]*entity.LabRequest, error)

	// Count counts total lab requests
	Count(ctx context.Context) (int64, error)

	// GetRecentCVEs retrieves recent CVEs for quick pick selection
	GetRecentCVEs(ctx context.Context, limit int) ([]*entity.RecentCVE, error)

	// GetCVEByID retrieves a specific CVE by its ID
	GetCVEByID(ctx context.Context, cveID string) (*entity.RecentCVE, error)

	// UpdateExpiredLabs updates the status of expired labs
	UpdateExpiredLabs(ctx context.Context) (int64, error)
}
