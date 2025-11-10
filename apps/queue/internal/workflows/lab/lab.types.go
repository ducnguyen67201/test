package lab

// LabProvisionParams contains the parameters for starting a lab provisioning workflow
type LabProvisionParams struct {
	LabID          string
	RequestedBy    string
	CVEID          string
	Severity       string
	TTLHours       int
	RequiresReview bool
}

// LabProvisionResult contains the result of a lab provisioning workflow
type LabProvisionResult struct {
	Success bool
	LabID   string
	Message string
}

// Blueprint represents the generated lab environment plan
type Blueprint struct {
	Summary      string
	RiskBadge    string
	LabID        string
	CVEID        string
	// Additional fields can be added as needed
}

// ProvisionResult contains the result of environment provisioning
type ProvisionResult struct {
	Success bool
	JobID   string
	Details map[string]interface{}
	Message string
}

// ReviewResult contains the result of human review
type ReviewResult struct {
	Approved bool
	Notes    string
	ReviewedBy string
}

// WorkflowStatus represents the current status of the workflow
type WorkflowStatus struct {
	CurrentPhase    string
	PercentComplete int
	Message         string
}
