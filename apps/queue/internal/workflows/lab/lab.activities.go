package lab

import (
	"context"
	"fmt"
	"time"

	"github.com/zerozero/apps/queue/internal/clients"
	"github.com/zerozero/apps/queue/pkg/logger"
	"go.temporal.io/sdk/activity"
)

// Activities contains all lab workflow activities
// All activities make gRPC calls to apps/api or provisioner service
// Activities are READ-ONLY - all mutations via gRPC
type Activities struct {
	apiClient         *clients.APIClient
	provisionerClient *clients.ProvisionerClient
	log               logger.Logger
}

// LockLab marks the lab as queued (gRPC: UpdateLabStatus)
func (a *Activities) LockLab(ctx context.Context, labID string) error {
	a.log.Info("Activity: LockLab", logger.String("lab_id", labID))

	// gRPC call to apps/api: UpdateLabStatus(labID, "queued")
	err := a.apiClient.UpdateLabStatus(ctx, labID, "queued", nil)
	if err != nil {
		a.log.Error("failed to lock lab via gRPC", logger.String("lab_id", labID), logger.Error(err))
		return fmt.Errorf("failed to lock lab: %w", err)
	}

	a.log.Info("lab locked successfully", logger.String("lab_id", labID))
	return nil
}

// GenerateBlueprint generates the lab environment blueprint (gRPC: GenerateBlueprint)
func (a *Activities) GenerateBlueprint(ctx context.Context, labID, cveID string) (*Blueprint, error) {
	a.log.Info("Activity: GenerateBlueprint",
		logger.String("lab_id", labID),
		logger.String("cve_id", cveID))

	// gRPC call to apps/api: GenerateBlueprint(labID)
	// Apps/API internally calls BlueprintService (existing logic)
	protoBlueprint, err := a.apiClient.GenerateBlueprint(ctx, labID)
	if err != nil {
		a.log.Error("failed to generate blueprint via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return nil, fmt.Errorf("failed to generate blueprint: %w", err)
	}

	// Convert proto blueprint to our internal type
	blueprint := &Blueprint{
		Summary:   protoBlueprint.Summary,
		RiskBadge: protoBlueprint.RiskBadge,
		LabID:     labID,
		CVEID:     cveID,
	}

	a.log.Info("blueprint generated successfully",
		logger.String("lab_id", labID),
		logger.String("summary", blueprint.Summary))

	return blueprint, nil
}

// ProvisionEnvironment provisions the lab environment (gRPC: ProvisionerService)
func (a *Activities) ProvisionEnvironment(ctx context.Context, labID, cveID string, blueprint Blueprint) (*ProvisionResult, error) {
	a.log.Info("Activity: ProvisionEnvironment",
		logger.String("lab_id", labID),
		logger.String("cve_id", cveID))

	// gRPC call to provisioner service: StartProvisioning(blueprint)
	jobID, err := a.provisionerClient.StartProvisioning(ctx, labID, cveID)
	if err != nil {
		a.log.Error("failed to start provisioning via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return nil, fmt.Errorf("failed to start provisioning: %w", err)
	}

	a.log.Info("provisioning job started",
		logger.String("lab_id", labID),
		logger.String("job_id", jobID))

	// Poll for completion with heartbeats
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			a.log.Warn("provisioning context cancelled", logger.String("lab_id", labID))
			return nil, ctx.Err()

		case <-ticker.C:
			// Record heartbeat so Temporal knows the activity is alive
			activity.RecordHeartbeat(ctx, map[string]interface{}{
				"job_id": jobID,
				"phase":  "provisioning",
			})

			// Read-only status check via gRPC
			status, err := a.provisionerClient.GetProvisioningStatus(ctx, jobID)
			if err != nil {
				a.log.Error("failed to get provisioning status",
					logger.String("job_id", jobID),
					logger.Error(err))
				continue // Retry on next tick
			}

			a.log.Info("provisioning status",
				logger.String("job_id", jobID),
				logger.String("current_step", status.CurrentStep),
				logger.Int("progress", int(status.ProgressPercent)))

			if status.Failed {
				errMsg := fmt.Sprintf("provisioning failed: %s", status.ErrorMessage)
				a.log.Error(errMsg, logger.String("job_id", jobID))
				return nil, fmt.Errorf(errMsg)
			}

			if status.Complete {
				// Update lab with provisioning details via gRPC
				// Convert details to map
				var details map[string]interface{}
				if status.Details != nil {
					details = status.Details.AsMap()
					err = a.apiClient.UpdateLabProvisioningDetails(ctx, labID, details)
					if err != nil {
						a.log.Warn("failed to update provisioning details",
							logger.String("lab_id", labID),
							logger.Error(err))
					}
				}

				a.log.Info("provisioning completed successfully",
					logger.String("lab_id", labID),
					logger.String("job_id", jobID))

				return &ProvisionResult{
					Success: true,
					JobID:   jobID,
					Details: details,
					Message: "Environment provisioned successfully",
				}, nil
			}
		}
	}
}

// RunValidation runs validation checks on the provisioned environment (gRPC: ValidateEnvironment)
func (a *Activities) RunValidation(ctx context.Context, labID, jobID string) error {
	a.log.Info("Activity: RunValidation",
		logger.String("lab_id", labID),
		logger.String("job_id", jobID))

	// gRPC call to provisioner service: ValidateEnvironment(labID, jobID)
	err := a.provisionerClient.ValidateEnvironment(ctx, labID, jobID)
	if err != nil {
		a.log.Error("validation failed via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return fmt.Errorf("validation failed: %w", err)
	}

	a.log.Info("validation completed successfully", logger.String("lab_id", labID))
	return nil
}

// FinalizeLab marks the lab as running (gRPC: UpdateLabStatus)
func (a *Activities) FinalizeLab(ctx context.Context, labID string) error {
	a.log.Info("Activity: FinalizeLab", logger.String("lab_id", labID))

	// gRPC call to apps/api: UpdateLabStatus(labID, "running")
	// Apps/API calculates expires_at internally using existing logic
	err := a.apiClient.UpdateLabStatus(ctx, labID, "running", nil)
	if err != nil {
		a.log.Error("failed to finalize lab via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return fmt.Errorf("failed to finalize lab: %w", err)
	}

	a.log.Info("lab finalized successfully", logger.String("lab_id", labID))
	return nil
}

// RejectLab marks the lab as rejected (gRPC: UpdateLabStatus)
func (a *Activities) RejectLab(ctx context.Context, labID, notes string) error {
	a.log.Info("Activity: RejectLab",
		logger.String("lab_id", labID),
		logger.String("notes", notes))

	// gRPC call to apps/api: UpdateLabStatus(labID, "rejected", notes)
	err := a.apiClient.UpdateLabStatus(ctx, labID, "rejected", &notes)
	if err != nil {
		a.log.Error("failed to reject lab via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return fmt.Errorf("failed to reject lab: %w", err)
	}

	a.log.Info("lab rejected successfully",
		logger.String("lab_id", labID),
		logger.String("reason", notes))
	return nil
}
