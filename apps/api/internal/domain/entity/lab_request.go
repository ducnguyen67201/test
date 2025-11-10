package entity

import (
	"encoding/json"
	"time"
)

// LabSource represents how a lab was initiated
type LabSource string

const (
	LabSourceQuickPick LabSource = "quick_pick"
	LabSourceManual    LabSource = "manual"
)

// LabSeverity represents the severity level of a CVE
type LabSeverity string

const (
	LabSeverityLow      LabSeverity = "low"
	LabSeverityMedium   LabSeverity = "medium"
	LabSeverityHigh     LabSeverity = "high"
	LabSeverityCritical LabSeverity = "critical"
)

// LabStatus represents the current status of a lab request
type LabStatus string

const (
	LabStatusDraft            LabStatus = "draft"
	LabStatusPendingGuardrail LabStatus = "pending_guardrail"
	LabStatusRejected         LabStatus = "rejected"
	LabStatusQueued           LabStatus = "queued"
	LabStatusRunning          LabStatus = "running"
	LabStatusCompleted        LabStatus = "completed"
	LabStatusExpired          LabStatus = "expired"
)

// UserRole represents the role of a user (for TTL override permissions)
type UserRole string

const (
	UserRoleUser  UserRole = "user"
	UserRoleAdmin UserRole = "admin"
)

// LabRequest represents a user request for a CVE analysis lab
type LabRequest struct {
	ID                 string          `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
	UserID             string          `gorm:"type:uuid;not null;index" json:"user_id"`
	Source             LabSource       `gorm:"type:lab_source;not null" json:"source"`
	CVEID              string          `gorm:"type:varchar(50)" json:"cve_id"`
	Title              string          `gorm:"type:varchar(500);not null" json:"title"`
	Severity           LabSeverity     `gorm:"type:lab_severity;not null" json:"severity"`
	Description        string          `gorm:"type:text" json:"description"`
	Objective          string          `gorm:"type:text" json:"objective"`
	TTLHours           int             `gorm:"type:int;not null;default:4" json:"ttl_hours"`
	ExpiresAt          *time.Time      `gorm:"type:timestamp;index" json:"expires_at"`
	Status             LabStatus       `gorm:"type:lab_status;not null;default:'draft';index" json:"status"`
	Blueprint          json.RawMessage `gorm:"type:jsonb" json:"blueprint"`
	GuardrailSnapshot  json.RawMessage `gorm:"type:jsonb" json:"guardrail_snapshot"`
	RiskRating         json.RawMessage `gorm:"type:jsonb" json:"risk_rating"`
	WorkflowID         *string         `gorm:"type:varchar(255);index:idx_lab_requests_workflow_id" json:"workflow_id,omitempty"`
	RunID              *string         `gorm:"type:varchar(255)" json:"run_id,omitempty"`
	CreatedAt          time.Time       `gorm:"autoCreateTime;index" json:"created_at"`
	UpdatedAt          time.Time       `gorm:"autoUpdateTime" json:"updated_at"`
}

// TableName specifies the table name for GORM
func (LabRequest) TableName() string {
	return "lab_requests"
}

// RecentCVE represents a CVE entry for quick pick selection
type RecentCVE struct {
	ID                   string      `gorm:"type:varchar(50);primary_key" json:"id"`
	Title                string      `gorm:"type:varchar(500);not null" json:"title"`
	Severity             LabSeverity `gorm:"type:lab_severity;not null;index" json:"severity"`
	PublishedAt          time.Time   `gorm:"type:timestamp;not null;index" json:"published_at"`
	ExploitabilityScore  float64     `gorm:"type:decimal(3,1)" json:"exploitability_score"`
	Description          string      `gorm:"type:text" json:"description"`
	CreatedAt            time.Time   `gorm:"autoCreateTime" json:"created_at"`
}

// TableName specifies the table name for GORM
func (RecentCVE) TableName() string {
	return "recent_cves"
}

// Blueprint represents the structured lab setup instructions
type Blueprint struct {
	Summary          string             `json:"summary"`
	RiskBadge        RiskBadge          `json:"risk_badge"`
	EnvironmentPlan  EnvironmentPlan    `json:"environment_plan"`
	ValidationSteps  []string           `json:"validation_steps"`
	AutomationHooks  []AutomationHook   `json:"automation_hooks"`
}

// RiskBadge represents the risk assessment
type RiskBadge struct {
	Level  LabSeverity `json:"level"`
	Reason string      `json:"reason"`
}

// EnvironmentPlan describes the lab environment setup
type EnvironmentPlan struct {
	BaseImage    string            `json:"base_image"`
	Dependencies []string          `json:"dependencies"`
	Configuration map[string]string `json:"configuration"`
}

// AutomationHook represents an automated action
type AutomationHook struct {
	Name    string `json:"name"`
	Command string `json:"command"`
	Stage   string `json:"stage"`
}

// GuardrailSnapshot captures the state of guardrail checks
type GuardrailSnapshot struct {
	Passed      bool               `json:"passed"`
	Checks      []GuardrailCheck   `json:"checks"`
	Timestamp   time.Time          `json:"timestamp"`
}

// GuardrailCheck represents a single guardrail validation
type GuardrailCheck struct {
	Name        string `json:"name"`
	Passed      bool   `json:"passed"`
	Message     string `json:"message"`
	Severity    string `json:"severity"` // "error", "warning", "info"
}

// RiskRating contains the risk assessment
type RiskRating struct {
	Score         float64 `json:"score"`
	Justification string  `json:"justification"`
	ReviewedBy    string  `json:"reviewed_by,omitempty"`
}

// Validate validates the lab request entity
func (lr *LabRequest) Validate() error {
	if lr.UserID == "" {
		return NewValidationError("user_id", "User ID is required")
	}
	if lr.Title == "" {
		return NewValidationError("title", "Title is required")
	}
	if lr.Source == "" {
		return NewValidationError("source", "Source is required")
	}
	if lr.Severity == "" {
		return NewValidationError("severity", "Severity is required")
	}
	if lr.TTLHours <= 0 {
		return NewValidationError("ttl_hours", "TTL must be greater than 0")
	}
	if lr.TTLHours > 8 {
		return NewValidationError("ttl_hours", "TTL cannot exceed 8 hours")
	}
	return nil
}

// CalculateExpiresAt calculates the expiration timestamp based on TTL
func (lr *LabRequest) CalculateExpiresAt() time.Time {
	return time.Now().Add(time.Duration(lr.TTLHours) * time.Hour)
}

// IsActive checks if the lab is currently active (queued or running)
func (lr *LabRequest) IsActive() bool {
	return lr.Status == LabStatusQueued || lr.Status == LabStatusRunning
}

// IsExpired checks if the lab has expired
func (lr *LabRequest) IsExpired() bool {
	if lr.ExpiresAt == nil {
		return false
	}
	return time.Now().After(*lr.ExpiresAt)
}

// RequiresJustification checks if this severity level requires justification
func (s LabSeverity) RequiresJustification() bool {
	return s == LabSeverityCritical
}

// RequiresApproval checks if this severity level requires approval
func (s LabSeverity) RequiresApproval() bool {
	return s == LabSeverityHigh || s == LabSeverityCritical
}

// String implements the Stringer interface for LabSource
func (ls LabSource) String() string {
	return string(ls)
}

// String implements the Stringer interface for LabSeverity
func (ls LabSeverity) String() string {
	return string(ls)
}

// String implements the Stringer interface for LabStatus
func (ls LabStatus) String() string {
	return string(ls)
}
