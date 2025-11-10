package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Workflow metrics
var (
	WorkflowsStarted = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "temporal_workflows_started_total",
			Help: "Total number of workflows started",
		},
		[]string{"workflow_type"},
	)

	WorkflowsCompleted = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "temporal_workflows_completed_total",
			Help: "Total number of workflows completed",
		},
		[]string{"workflow_type", "status"},
	)

	WorkflowDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "temporal_workflow_duration_seconds",
			Help:    "Workflow execution duration in seconds",
			Buckets: prometheus.ExponentialBuckets(1, 2, 10), // 1s to ~17 minutes
		},
		[]string{"workflow_type"},
	)
)

// Activity metrics
var (
	ActivityDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "temporal_activity_duration_seconds",
			Help:    "Activity execution duration in seconds",
			Buckets: prometheus.ExponentialBuckets(0.1, 2, 10), // 100ms to ~1.7 minutes
		},
		[]string{"activity_name"},
	)

	ActivityErrors = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "temporal_activity_errors_total",
			Help: "Total number of activity errors",
		},
		[]string{"activity_name", "error_type"},
	)

	ActivityRetries = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "temporal_activity_retries_total",
			Help: "Total number of activity retries",
		},
		[]string{"activity_name"},
	)
)

// gRPC metrics
var (
	GRPCCalls = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "grpc_client_calls_total",
			Help: "Total number of gRPC client calls",
		},
		[]string{"service", "method", "status"},
	)

	GRPCDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "grpc_client_duration_seconds",
			Help:    "gRPC call duration in seconds",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"service", "method"},
	)
)

// Worker metrics
var (
	ActiveWorkers = promauto.NewGauge(
		prometheus.GaugeOpts{
			Name: "temporal_active_workers",
			Help: "Number of active Temporal workers",
		},
	)

	TaskQueueDepth = promauto.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "temporal_task_queue_depth",
			Help: "Current depth of the task queue",
		},
		[]string{"task_queue"},
	)
)

// Lab-specific metrics
var (
	LabsProvisioned = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "labs_provisioned_total",
			Help: "Total number of labs provisioned",
		},
		[]string{"severity", "status"},
	)

	LabProvisioningDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "lab_provisioning_duration_seconds",
			Help:    "Lab provisioning duration in seconds",
			Buckets: prometheus.ExponentialBuckets(10, 2, 10), // 10s to ~2.8 hours
		},
		[]string{"severity"},
	)
)
