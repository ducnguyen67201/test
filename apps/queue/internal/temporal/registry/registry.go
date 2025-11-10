package registry

import (
	"go.temporal.io/sdk/worker"
)

// Registrar defines the interface for workflow/activity registration
// Each workflow package implements this interface to register its workflows and activities
type Registrar interface {
	// TaskQueue returns the task queue name this registrar handles
	TaskQueue() string

	// Register registers all workflows and activities with the worker
	Register(w worker.Worker)
}

// RegisterAll registers all workflows/activities from the provided registrars
// It filters registrars by task queue to allow different workers to handle different queues
func RegisterAll(w worker.Worker, registrars []Registrar, taskQueue string) {
	for _, r := range registrars {
		if r.TaskQueue() == taskQueue {
			r.Register(w)
		}
	}
}
