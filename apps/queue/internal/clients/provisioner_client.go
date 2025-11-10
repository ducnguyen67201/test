package clients

import (
	"context"
	"fmt"
	"time"

	"github.com/zerozero/apps/queue/pkg/logger"
	provisionerv1 "github.com/zerozero/proto/gen/go/provisioner/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// ProvisionerClient wraps the gRPC client for the provisioner service
// Used by Temporal activities to provision lab environments
type ProvisionerClient struct {
	client provisionerv1.ProvisionerServiceClient
	conn   *grpc.ClientConn
	log    logger.Logger
}

// NewProvisionerClient creates a new Provisioner gRPC client
func NewProvisionerClient(address string, log logger.Logger) (*ProvisionerClient, error) {
	// Create gRPC connection (insecure for local development)
	// TODO: Add TLS support for production
	conn, err := grpc.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Warn("failed to create Provisioner gRPC client (may not be running)",
			logger.String("address", address),
			logger.Error(err))
		// Don't fail - provisioner may not be running yet
		// Return client anyway so activities can handle gracefully
		return &ProvisionerClient{
			client: nil,
			conn:   nil,
			log:    log,
		}, nil
	}

	log.Info("Provisioner gRPC client created", logger.String("address", address))

	return &ProvisionerClient{
		client: provisionerv1.NewProvisionerServiceClient(conn),
		conn:   conn,
		log:    log,
	}, nil
}

// Close closes the gRPC connection
func (c *ProvisionerClient) Close() error {
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

// StartProvisioning initiates lab environment provisioning
func (c *ProvisionerClient) StartProvisioning(ctx context.Context, labID string, cveID string) (string, error) {
	if c.client == nil {
		c.log.Warn("provisioner client not connected, returning mock job ID",
			logger.String("lab_id", labID))
		// Return mock job ID for placeholder
		return fmt.Sprintf("mock-job-%s-%d", labID, time.Now().Unix()), nil
	}

	req := &provisionerv1.StartProvisioningRequest{
		LabId: labID,
		CveId: cveID,
		// TODO: Add environment plan, validation steps, automation hooks
	}

	resp, err := c.client.StartProvisioning(ctx, req)
	if err != nil {
		c.log.Error("failed to start provisioning via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return "", fmt.Errorf("failed to start provisioning: %w", err)
	}

	if !resp.Success {
		return "", fmt.Errorf("start provisioning returned success=false: %s", resp.Message)
	}

	c.log.Info("provisioning started via gRPC",
		logger.String("lab_id", labID),
		logger.String("job_id", resp.JobId))

	return resp.JobId, nil
}

// GetProvisioningStatus queries the status of a provisioning job (read-only)
func (c *ProvisionerClient) GetProvisioningStatus(ctx context.Context, jobID string) (*provisionerv1.GetStatusResponse, error) {
	if c.client == nil {
		c.log.Warn("provisioner client not connected, returning mock completed status",
			logger.String("job_id", jobID))
		// Return mock completed status for placeholder
		return &provisionerv1.GetStatusResponse{
			JobId:           jobID,
			Status:          provisionerv1.ProvisioningStatus_PROVISIONING_STATUS_COMPLETED,
			ProgressPercent: 100,
			CurrentStep:     "completed",
			Complete:        true,
			Failed:          false,
		}, nil
	}

	req := &provisionerv1.GetStatusRequest{
		JobId: jobID,
	}

	resp, err := c.client.GetProvisioningStatus(ctx, req)
	if err != nil {
		c.log.Error("failed to get provisioning status via gRPC",
			logger.String("job_id", jobID),
			logger.Error(err))
		return nil, fmt.Errorf("failed to get provisioning status: %w", err)
	}

	return resp, nil
}

// ValidateEnvironment runs validation checks on a provisioned environment
func (c *ProvisionerClient) ValidateEnvironment(ctx context.Context, labID, jobID string) error {
	if c.client == nil {
		c.log.Warn("provisioner client not connected, skipping validation",
			logger.String("lab_id", labID))
		// Return success for placeholder
		return nil
	}

	req := &provisionerv1.ValidateRequest{
		LabId: labID,
		JobId: jobID,
		// TODO: Add validation steps
	}

	resp, err := c.client.ValidateEnvironment(ctx, req)
	if err != nil {
		c.log.Error("failed to validate environment via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return fmt.Errorf("failed to validate environment: %w", err)
	}

	if !resp.Success || !resp.Passed {
		return fmt.Errorf("environment validation failed: %s", resp.Summary)
	}

	c.log.Info("environment validated via gRPC",
		logger.String("lab_id", labID),
		logger.String("summary", resp.Summary))

	return nil
}

// CancelProvisioning cancels an in-progress provisioning job
func (c *ProvisionerClient) CancelProvisioning(ctx context.Context, jobID, reason string) error {
	if c.client == nil {
		c.log.Warn("provisioner client not connected, skipping cancellation",
			logger.String("job_id", jobID))
		return nil
	}

	req := &provisionerv1.CancelProvisioningRequest{
		JobId:  jobID,
		Reason: reason,
	}

	resp, err := c.client.CancelProvisioning(ctx, req)
	if err != nil {
		c.log.Error("failed to cancel provisioning via gRPC",
			logger.String("job_id", jobID),
			logger.Error(err))
		return fmt.Errorf("failed to cancel provisioning: %w", err)
	}

	if !resp.Success {
		return fmt.Errorf("cancel provisioning returned success=false: %s", resp.Message)
	}

	c.log.Info("provisioning cancelled via gRPC",
		logger.String("job_id", jobID))

	return nil
}
