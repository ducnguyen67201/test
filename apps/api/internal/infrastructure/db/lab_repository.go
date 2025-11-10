package db

import (
	"context"

	"github.com/google/uuid"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/pkg/errors"
	"gorm.io/gorm"
)

// LabRepository is the GORM implementation of the lab repository
type LabRepository struct {
	db *gorm.DB
}

// NewLabRepository creates a new lab repository using GORM
func NewLabRepository(db *gorm.DB) repository.LabRepository {
	return &LabRepository{
		db: db,
	}
}

// GetByID implements repository.LabRepository
func (r *LabRepository) GetByID(ctx context.Context, id string) (*entity.LabRequest, error) {
	var lab entity.LabRequest
	err := r.db.WithContext(ctx).Where("id = ?", id).First(&lab).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("Lab request")
		}
		return nil, errors.NewDatabaseError("Failed to get lab request by ID").WithError(err)
	}
	return &lab, nil
}

// GetByUserID implements repository.LabRepository
func (r *LabRepository) GetByUserID(ctx context.Context, userID string, limit, offset int) ([]*entity.LabRequest, error) {
	var labs []*entity.LabRequest
	err := r.db.WithContext(ctx).
		Where("user_id = ?", userID).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&labs).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get lab requests by user ID").WithError(err)
	}

	return labs, nil
}

// GetActiveByUserID implements repository.LabRepository
func (r *LabRepository) GetActiveByUserID(ctx context.Context, userID string) ([]*entity.LabRequest, error) {
	var labs []*entity.LabRequest
	err := r.db.WithContext(ctx).
		Where("user_id = ? AND status IN ?", userID, []string{"queued", "running"}).
		Order("created_at DESC").
		Find(&labs).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get active lab requests").WithError(err)
	}

	return labs, nil
}

// CountActiveByUserID implements repository.LabRepository
func (r *LabRepository) CountActiveByUserID(ctx context.Context, userID string) (int64, error) {
	var count int64
	err := r.db.WithContext(ctx).
		Model(&entity.LabRequest{}).
		Where("user_id = ? AND status IN ?", userID, []string{"queued", "running"}).
		Count(&count).Error

	if err != nil {
		return 0, errors.NewDatabaseError("Failed to count active lab requests").WithError(err)
	}

	return count, nil
}

// Create implements repository.LabRepository
func (r *LabRepository) Create(ctx context.Context, labRequest *entity.LabRequest) (*entity.LabRequest, error) {
	if labRequest.ID == "" {
		labRequest.ID = uuid.New().String()
	}

	err := r.db.WithContext(ctx).Create(labRequest).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to create lab request").WithError(err)
	}

	return labRequest, nil
}

// Update implements repository.LabRepository
func (r *LabRepository) Update(ctx context.Context, labRequest *entity.LabRequest) (*entity.LabRequest, error) {
	err := r.db.WithContext(ctx).Save(labRequest).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to update lab request").WithError(err)
	}

	// Check if lab exists
	var count int64
	r.db.WithContext(ctx).Model(&entity.LabRequest{}).Where("id = ?", labRequest.ID).Count(&count)
	if count == 0 {
		return nil, errors.NewNotFound("Lab request")
	}

	return labRequest, nil
}

// Delete implements repository.LabRepository
func (r *LabRepository) Delete(ctx context.Context, id string) error {
	result := r.db.WithContext(ctx).Delete(&entity.LabRequest{}, "id = ?", id)
	if result.Error != nil {
		return errors.NewDatabaseError("Failed to delete lab request").WithError(result.Error)
	}

	if result.RowsAffected == 0 {
		return errors.NewNotFound("Lab request")
	}

	return nil
}

// List implements repository.LabRepository
func (r *LabRepository) List(ctx context.Context, limit, offset int) ([]*entity.LabRequest, error) {
	var labs []*entity.LabRequest
	err := r.db.WithContext(ctx).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&labs).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to list lab requests").WithError(err)
	}

	return labs, nil
}

// Count implements repository.LabRepository
func (r *LabRepository) Count(ctx context.Context) (int64, error) {
	var count int64
	err := r.db.WithContext(ctx).Model(&entity.LabRequest{}).Count(&count).Error
	if err != nil {
		return 0, errors.NewDatabaseError("Failed to count lab requests").WithError(err)
	}

	return count, nil
}

// GetRecentCVEs implements repository.LabRepository
func (r *LabRepository) GetRecentCVEs(ctx context.Context, limit int) ([]*entity.RecentCVE, error) {
	var cves []*entity.RecentCVE
	err := r.db.WithContext(ctx).
		Order("published_at DESC").
		Limit(limit).
		Find(&cves).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get recent CVEs").WithError(err)
	}

	return cves, nil
}

// GetCVEByID implements repository.LabRepository
func (r *LabRepository) GetCVEByID(ctx context.Context, cveID string) (*entity.RecentCVE, error) {
	var cve entity.RecentCVE
	err := r.db.WithContext(ctx).Where("id = ?", cveID).First(&cve).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("CVE")
		}
		return nil, errors.NewDatabaseError("Failed to get CVE by ID").WithError(err)
	}

	return &cve, nil
}

// UpdateExpiredLabs implements repository.LabRepository
func (r *LabRepository) UpdateExpiredLabs(ctx context.Context) (int64, error) {
	result := r.db.WithContext(ctx).
		Model(&entity.LabRequest{}).
		Where("expires_at < NOW() AND status IN ?", []string{"queued", "running"}).
		Update("status", "expired")

	if result.Error != nil {
		return 0, errors.NewDatabaseError("Failed to update expired labs").WithError(result.Error)
	}

	return result.RowsAffected, nil
}
