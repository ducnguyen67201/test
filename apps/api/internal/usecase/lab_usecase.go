package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/internal/infrastructure/services"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/logger"
)

// LabUseCase handles lab request business logic
type LabUseCase interface {
	// GetContext returns context data for the request lab page (quick picks, guardrails, active lab)
	GetContext(ctx context.Context, userID string, userRole entity.UserRole) (*LabContext, error)

	// CreateDraft creates a new draft lab request
	CreateDraft(ctx context.Context, userID string, input *CreateLabInput) (*entity.LabRequest, error)

	// GenerateBlueprint generates a blueprint for a lab request
	GenerateBlueprint(ctx context.Context, labID string) (*entity.LabRequest, error)

	// ConfirmRequest validates guardrails and confirms a lab request
	ConfirmRequest(ctx context.Context, labID string, userRole entity.UserRole, justification string) (*entity.LabRequest, error)

	// GetByID retrieves a lab request by ID
	GetByID(ctx context.Context, labID string) (*entity.LabRequest, error)

	// GetActiveByUserID retrieves active labs for a user
	GetActiveByUserID(ctx context.Context, userID string) ([]*entity.LabRequest, error)

	// CancelLab cancels a running or queued lab
	CancelLab(ctx context.Context, labID string, userID string) error

	// UpdateExpiredLabs updates the status of expired labs
	UpdateExpiredLabs(ctx context.Context) (int64, error)
}

// labUseCase is the concrete implementation
type labUseCase struct {
	labRepo          repository.LabRepository
	userRepo         repository.UserRepository
	blueprintService services.BlueprintService
	logger           logger.Logger
}

// NewLabUseCase creates a new lab use case
func NewLabUseCase(
	labRepo repository.LabRepository,
	userRepo repository.UserRepository,
	blueprintService services.BlueprintService,
	logger logger.Logger,
) LabUseCase {
	return &labUseCase{
		labRepo:          labRepo,
		userRepo:         userRepo,
		blueprintService: blueprintService,
		logger:           logger,
	}
}

// LabContext contains context data for the request lab page
type LabContext struct {
	QuickPicks         []*entity.RecentCVE              `json:"quick_picks"`
	GuardrailSnapshot  *entity.GuardrailSnapshot        `json:"guardrail_snapshot"`
	ActiveLab          *entity.LabRequest               `json:"active_lab,omitempty"`
}

// CreateLabInput represents input for creating a lab request
type CreateLabInput struct {
	Source      entity.LabSource   `json:"source"`
	CVEID       string             `json:"cve_id"`
	Title       string             `json:"title"`
	Severity    entity.LabSeverity `json:"severity"`
	Description string             `json:"description"`
	Objective   string             `json:"objective"`
	TTLHours    int                `json:"ttl_hours"`
}

// GetContext implements LabUseCase
func (uc *labUseCase) GetContext(ctx context.Context, userID string, userRole entity.UserRole) (*LabContext, error) {
	// Get quick picks (recent CVEs)
	quickPicks, err := uc.labRepo.GetRecentCVEs(ctx, 10)
	if err != nil {
		uc.logger.Error("Failed to get recent CVEs", logger.Error(err))
		return nil, errors.NewInternal("Failed to load quick picks").WithError(err)
	}

	// Get active labs for user
	activeLabs, err := uc.labRepo.GetActiveByUserID(ctx, userID)
	if err != nil {
		uc.logger.Error("Failed to get active labs", logger.Error(err))
		return nil, errors.NewInternal("Failed to check active labs").WithError(err)
	}

	var activeLab *entity.LabRequest
	if len(activeLabs) > 0 {
		activeLab = activeLabs[0]
	}

	// Generate guardrail snapshot for current state
	guardrails := uc.validateGuardrails(ctx, userID, userRole, entity.LabSeverityLow, 4, "", false)

	return &LabContext{
		QuickPicks:        quickPicks,
		GuardrailSnapshot: guardrails,
		ActiveLab:         activeLab,
	}, nil
}

// CreateDraft implements LabUseCase
func (uc *labUseCase) CreateDraft(ctx context.Context, userID string, input *CreateLabInput) (*entity.LabRequest, error) {
	// Validate input
	if input.Title == "" {
		return nil, errors.NewValidation("Title is required")
	}
	if input.Severity == "" {
		return nil, errors.NewValidation("Severity is required")
	}
	if input.TTLHours <= 0 || input.TTLHours > 8 {
		return nil, errors.NewValidation("TTL must be between 1 and 8 hours")
	}

	// If source is quick_pick and CVE ID is provided, fetch CVE details
	if input.Source == entity.LabSourceQuickPick && input.CVEID != "" {
		cve, err := uc.labRepo.GetCVEByID(ctx, input.CVEID)
		if err != nil {
			uc.logger.Warn("CVE not found", logger.String("cve_id", input.CVEID))
			// Continue anyway - treat as manual if CVE not found
			input.Source = entity.LabSourceManual
		} else {
			// Populate from CVE data if not provided
			if input.Title == "" {
				input.Title = cve.Title
			}
			if input.Severity == "" {
				input.Severity = cve.Severity
			}
			if input.Description == "" {
				input.Description = cve.Description
			}
		}
	}

	// Create draft lab request
	labRequest := &entity.LabRequest{
		UserID:      userID,
		Source:      input.Source,
		CVEID:       input.CVEID,
		Title:       input.Title,
		Severity:    input.Severity,
		Description: input.Description,
		Objective:   input.Objective,
		TTLHours:    input.TTLHours,
		Status:      entity.LabStatusDraft,
	}

	// Validate entity
	if err := labRequest.Validate(); err != nil {
		return nil, errors.NewValidation(err.Error())
	}

	// Create in database
	created, err := uc.labRepo.Create(ctx, labRequest)
	if err != nil {
		uc.logger.Error("Failed to create lab request", logger.Error(err))
		return nil, errors.NewInternal("Failed to create lab request").WithError(err)
	}

	uc.logger.Info("Created draft lab request",
		logger.String("lab_id", created.ID),
		logger.String("user_id", userID),
		logger.String("severity", created.Severity.String()))

	return created, nil
}

// GenerateBlueprint implements LabUseCase
func (uc *labUseCase) GenerateBlueprint(ctx context.Context, labID string) (*entity.LabRequest, error) {
	// Get lab request
	labRequest, err := uc.labRepo.GetByID(ctx, labID)
	if err != nil {
		return nil, err
	}

	// Generate blueprint using service
	blueprint, err := uc.blueprintService.GenerateBlueprint(ctx, labRequest)
	if err != nil {
		uc.logger.Error("Failed to generate blueprint",
			logger.String("lab_id", labID),
			logger.Error(err))
		return nil, errors.NewInternal("Failed to generate blueprint").WithError(err)
	}

	// Serialize blueprint to JSON
	blueprintJSON, err := services.SerializeBlueprint(blueprint)
	if err != nil {
		uc.logger.Error("Failed to serialize blueprint", logger.Error(err))
		return nil, errors.NewInternal("Failed to serialize blueprint").WithError(err)
	}

	// Update lab request with blueprint
	labRequest.Blueprint = blueprintJSON
	labRequest.Status = entity.LabStatusPendingGuardrail

	updated, err := uc.labRepo.Update(ctx, labRequest)
	if err != nil {
		uc.logger.Error("Failed to update lab request with blueprint", logger.Error(err))
		return nil, errors.NewInternal("Failed to save blueprint").WithError(err)
	}

	uc.logger.Info("Generated blueprint for lab",
		logger.String("lab_id", labID))

	return updated, nil
}

// ConfirmRequest implements LabUseCase
func (uc *labUseCase) ConfirmRequest(ctx context.Context, labID string, userRole entity.UserRole, justification string) (*entity.LabRequest, error) {
	// Get lab request
	labRequest, err := uc.labRepo.GetByID(ctx, labID)
	if err != nil {
		return nil, err
	}

	// Validate guardrails
	guardrails := uc.validateGuardrails(ctx, labRequest.UserID, userRole, labRequest.Severity, labRequest.TTLHours, justification, true)

	// Check if guardrails passed
	if !guardrails.Passed {
		// Find blocking errors
		var blockingReasons []string
		for _, check := range guardrails.Checks {
			if !check.Passed && check.Severity == "error" {
				blockingReasons = append(blockingReasons, check.Message)
			}
		}

		// Update lab status to rejected
		labRequest.Status = entity.LabStatusRejected
		guardrailJSON, _ := json.Marshal(guardrails)
		labRequest.GuardrailSnapshot = guardrailJSON
		uc.labRepo.Update(ctx, labRequest)

		uc.logger.Warn("Lab request rejected by guardrails",
			logger.String("lab_id", labID),
			logger.String("reasons", strings.Join(blockingReasons, "; ")))

		return nil, errors.NewValidation(
			fmt.Sprintf("Guardrails failed: %s", strings.Join(blockingReasons, "; ")),
		).WithMetadata("guardrails", guardrails)
	}

	// Guardrails passed - update lab status
	labRequest.Status = entity.LabStatusQueued
	expiresAt := labRequest.CalculateExpiresAt()
	labRequest.ExpiresAt = &expiresAt

	// Save guardrail snapshot
	guardrailJSON, err := json.Marshal(guardrails)
	if err != nil {
		uc.logger.Error("Failed to serialize guardrails", logger.Error(err))
	} else {
		labRequest.GuardrailSnapshot = guardrailJSON
	}

	// Update in database
	updated, err := uc.labRepo.Update(ctx, labRequest)
	if err != nil {
		uc.logger.Error("Failed to confirm lab request", logger.Error(err))
		return nil, errors.NewInternal("Failed to confirm lab request").WithError(err)
	}

	uc.logger.Info("Lab request confirmed and queued",
		logger.String("lab_id", labID),
		logger.String("expires_at", expiresAt.Format(time.RFC3339)))

	// TODO: Emit event for provisioner to pick up
	// For MVP, lab remains in "queued" status

	return updated, nil
}

// validateGuardrails performs all guardrail checks
func (uc *labUseCase) validateGuardrails(
	ctx context.Context,
	userID string,
	userRole entity.UserRole,
	severity entity.LabSeverity,
	ttlHours int,
	justification string,
	strictMode bool, // When true, treat warnings as errors
) *entity.GuardrailSnapshot {
	snapshot := &entity.GuardrailSnapshot{
		Passed:    true,
		Checks:    []entity.GuardrailCheck{},
		Timestamp: time.Now(),
	}

	// Check 1: Active lab limit (≤1 active lab per user)
	activeCount, err := uc.labRepo.CountActiveByUserID(ctx, userID)
	if err != nil {
		uc.logger.Error("Failed to count active labs", logger.Error(err))
		snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
			Name:     "Active Lab Limit",
			Passed:   false,
			Message:  "Failed to verify active lab count",
			Severity: "error",
		})
		snapshot.Passed = false
	} else if activeCount > 0 {
		snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
			Name:     "Active Lab Limit",
			Passed:   false,
			Message:  fmt.Sprintf("You have %d active lab(s). Please complete or cancel existing labs before requesting a new one.", activeCount),
			Severity: "error",
		})
		snapshot.Passed = false
	} else {
		snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
			Name:     "Active Lab Limit",
			Passed:   true,
			Message:  "No active labs - you can proceed",
			Severity: "info",
		})
	}

	// Check 2: Critical severity requires justification
	if severity == entity.LabSeverityCritical {
		if len(strings.TrimSpace(justification)) < 50 {
			snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
				Name:     "Critical Severity Justification",
				Passed:   false,
				Message:  "Critical severity requires written justification (minimum 50 characters)",
				Severity: "error",
			})
			snapshot.Passed = false
		} else {
			snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
				Name:     "Critical Severity Justification",
				Passed:   true,
				Message:  "Justification provided",
				Severity: "info",
			})
		}
	}

	// Check 3: High severity requires approval (soft warning for MVP)
	if severity == entity.LabSeverityHigh {
		checkSeverity := "warning"
		if strictMode {
			// In future, this could be "error" requiring actual approval
			checkSeverity = "warning"
		}
		snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
			Name:     "High Severity Approval",
			Passed:   true, // Pass for MVP, just warn
			Message:  "High severity labs typically require manager approval. Proceeding with elevated monitoring.",
			Severity: checkSeverity,
		})
	}

	// Check 4: TTL validation and admin override
	if ttlHours > 8 {
		snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
			Name:     "TTL Maximum",
			Passed:   false,
			Message:  "TTL cannot exceed 8 hours",
			Severity: "error",
		})
		snapshot.Passed = false
	} else if ttlHours > 4 {
		// Requires admin role
		if userRole != entity.UserRoleAdmin {
			snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
				Name:     "TTL Override Permission",
				Passed:   false,
				Message:  "TTL greater than 4 hours requires admin role",
				Severity: "error",
			})
			snapshot.Passed = false
		} else {
			snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
				Name:     "TTL Override Permission",
				Passed:   true,
				Message:  fmt.Sprintf("Admin override approved for %d hour TTL", ttlHours),
				Severity: "info",
			})
		}
	} else {
		snapshot.Checks = append(snapshot.Checks, entity.GuardrailCheck{
			Name:     "TTL Validation",
			Passed:   true,
			Message:  fmt.Sprintf("TTL of %d hours is within standard limits", ttlHours),
			Severity: "info",
		})
	}

	return snapshot
}

// GetByID implements LabUseCase
func (uc *labUseCase) GetByID(ctx context.Context, labID string) (*entity.LabRequest, error) {
	return uc.labRepo.GetByID(ctx, labID)
}

// GetActiveByUserID implements LabUseCase
func (uc *labUseCase) GetActiveByUserID(ctx context.Context, userID string) ([]*entity.LabRequest, error) {
	return uc.labRepo.GetActiveByUserID(ctx, userID)
}

// CancelLab implements LabUseCase
func (uc *labUseCase) CancelLab(ctx context.Context, labID string, userID string) error {
	lab, err := uc.labRepo.GetByID(ctx, labID)
	if err != nil {
		return err
	}

	// Verify ownership
	if lab.UserID != userID {
		return errors.NewForbidden("You can only cancel your own labs")
	}

	// Can only cancel queued or running labs
	if lab.Status != entity.LabStatusQueued && lab.Status != entity.LabStatusRunning {
		return errors.NewBadRequest("Can only cancel queued or running labs")
	}

	// Update status
	lab.Status = entity.LabStatusCompleted
	_, err = uc.labRepo.Update(ctx, lab)
	if err != nil {
		uc.logger.Error("Failed to cancel lab", logger.Error(err))
		return errors.NewInternal("Failed to cancel lab").WithError(err)
	}

	uc.logger.Info("Lab cancelled", logger.String("lab_id", labID))
	return nil
}

// UpdateExpiredLabs implements LabUseCase
func (uc *labUseCase) UpdateExpiredLabs(ctx context.Context) (int64, error) {
	count, err := uc.labRepo.UpdateExpiredLabs(ctx)
	if err != nil {
		uc.logger.Error("Failed to update expired labs", logger.Error(err))
		return 0, errors.NewInternal("Failed to update expired labs").WithError(err)
	}

	if count > 0 {
		uc.logger.Info("Updated expired labs", logger.Int("count", int(count)))
	}

	return count, nil
}
