package lab

import (
	"github.com/zerozero/apps/queue/internal/clients"
	"github.com/zerozero/apps/queue/pkg/logger"
	"go.temporal.io/sdk/worker"
)

// Registrar implements the registry.Registrar interface for lab workflows
type Registrar struct {
	activities *Activities
	taskQueue  string
}

// NewRegistrar creates a new lab workflow registrar
func NewRegistrar(
	apiClient *clients.APIClient,
	provisionerClient *clients.ProvisionerClient,
	log logger.Logger,
	taskQueue string,
) *Registrar {
	return &Registrar{
		activities: &Activities{
			apiClient:         apiClient,
			provisionerClient: provisionerClient,
			log:               log,
		},
		taskQueue: taskQueue,
	}
}

// TaskQueue returns the task queue this registrar handles
func (r *Registrar) TaskQueue() string {
	return r.taskQueue
}

// Register registers all workflows and activities with the worker
func (r *Registrar) Register(w worker.Worker) {
	// Register workflow
	w.RegisterWorkflow(LabProvisionWorkflow)

	// Register activities
	w.RegisterActivity(r.activities.LockLab)
	w.RegisterActivity(r.activities.GenerateBlueprint)
	w.RegisterActivity(r.activities.ProvisionEnvironment)
	w.RegisterActivity(r.activities.RunValidation)
	w.RegisterActivity(r.activities.FinalizeLab)
	w.RegisterActivity(r.activities.RejectLab)
}
