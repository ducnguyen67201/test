package entity

import (
	"time"
)

// ChatSessionStatus represents the current status of a chat session
type ChatSessionStatus string

const (
	ChatSessionStatusOpen       ChatSessionStatus = "open"
	ChatSessionStatusFinalizing ChatSessionStatus = "finalizing"
	ChatSessionStatusClosed     ChatSessionStatus = "closed"
)

// ChatSession represents an LLM conversation session for recipe generation
type ChatSession struct {
	ID                   string            `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
	UserID               string            `gorm:"type:uuid;not null;index" json:"user_id"`
	ProjectID            *string           `gorm:"type:uuid" json:"project_id,omitempty"`
	Status               ChatSessionStatus `gorm:"type:chat_session_status;not null;default:'open';index" json:"status"`
	LLMModel             string            `gorm:"type:varchar(100);not null;default:'gpt-4o'" json:"llm_model"`
	TokenUsage           int               `gorm:"type:int;not null;default:0" json:"token_usage"`
	MaxTokens            int               `gorm:"type:int;not null;default:50000" json:"max_tokens"`
	MaxDurationMinutes   int               `gorm:"type:int;not null;default:30" json:"max_duration_minutes"`
	CreatedAt            time.Time         `gorm:"autoCreateTime;index" json:"created_at"`
	UpdatedAt            time.Time         `gorm:"autoUpdateTime" json:"updated_at"`
	ClosedAt             *time.Time        `gorm:"type:timestamp" json:"closed_at,omitempty"`
}

// TableName specifies the table name for GORM
func (ChatSession) TableName() string {
	return "chat_sessions"
}

// Validate validates the chat session entity
func (cs *ChatSession) Validate() error {
	if cs.UserID == "" {
		return NewValidationError("user_id", "User ID is required")
	}
	if cs.LLMModel == "" {
		return NewValidationError("llm_model", "LLM model is required")
	}
	if cs.MaxTokens <= 0 {
		return NewValidationError("max_tokens", "Max tokens must be greater than 0")
	}
	if cs.MaxDurationMinutes <= 0 {
		return NewValidationError("max_duration_minutes", "Max duration must be greater than 0")
	}
	return nil
}

// IsOpen checks if the session is currently open
func (cs *ChatSession) IsOpen() bool {
	return cs.Status == ChatSessionStatusOpen
}

// IsClosed checks if the session is closed
func (cs *ChatSession) IsClosed() bool {
	return cs.Status == ChatSessionStatusClosed
}

// IsOverBudget checks if the session has exceeded token budget
func (cs *ChatSession) IsOverBudget() bool {
	return cs.TokenUsage >= cs.MaxTokens
}

// IsOverDuration checks if the session has exceeded time limit
func (cs *ChatSession) IsOverDuration() bool {
	// Temporarily disabled for testing - sessions won't expire based on duration
	return false
	// maxDuration := time.Duration(cs.MaxDurationMinutes) * time.Minute
	// return time.Since(cs.CreatedAt) >= maxDuration
}

// ShouldAutoClose checks if session should be automatically closed
func (cs *ChatSession) ShouldAutoClose() bool {
	return cs.IsOverBudget() || cs.IsOverDuration()
}

// AddTokens adds tokens to the session usage count
func (cs *ChatSession) AddTokens(tokens int) {
	cs.TokenUsage += tokens
}

// Close closes the session
func (cs *ChatSession) Close() {
	cs.Status = ChatSessionStatusClosed
	now := time.Now()
	cs.ClosedAt = &now
}

// String implements the Stringer interface for ChatSessionStatus
func (css ChatSessionStatus) String() string {
	return string(css)
}
