package entity

import (
	"time"
)

// ChatMessageRole represents the sender of a chat message
type ChatMessageRole string

const (
	ChatMessageRoleUser      ChatMessageRole = "user"
	ChatMessageRoleAssistant ChatMessageRole = "assistant"
	ChatMessageRoleSystem    ChatMessageRole = "system"
)

// ChatMessage represents an individual message in a chat session
type ChatMessage struct {
	ID        string          `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
	SessionID string          `gorm:"type:uuid;not null;index" json:"session_id"`
	Role      ChatMessageRole `gorm:"type:chat_message_role;not null" json:"role"`
	Content   string          `gorm:"type:text;not null" json:"content"`
	Sequence  int             `gorm:"type:int;not null" json:"sequence"`
	Tokens    int             `gorm:"type:int;not null;default:0" json:"tokens"`
	CreatedAt time.Time       `gorm:"autoCreateTime;index" json:"created_at"`
}

// TableName specifies the table name for GORM
func (ChatMessage) TableName() string {
	return "chat_messages"
}

// Validate validates the chat message entity
func (cm *ChatMessage) Validate() error {
	if cm.SessionID == "" {
		return NewValidationError("session_id", "Session ID is required")
	}
	if cm.Role == "" {
		return NewValidationError("role", "Role is required")
	}
	if cm.Content == "" {
		return NewValidationError("content", "Content is required")
	}
	if cm.Sequence < 0 {
		return NewValidationError("sequence", "Sequence must be non-negative")
	}
	return nil
}

// IsUserMessage checks if the message is from a user
func (cm *ChatMessage) IsUserMessage() bool {
	return cm.Role == ChatMessageRoleUser
}

// IsAssistantMessage checks if the message is from the assistant
func (cm *ChatMessage) IsAssistantMessage() bool {
	return cm.Role == ChatMessageRoleAssistant
}

// IsSystemMessage checks if the message is a system prompt
func (cm *ChatMessage) IsSystemMessage() bool {
	return cm.Role == ChatMessageRoleSystem
}

// String implements the Stringer interface for ChatMessageRole
func (cmr ChatMessageRole) String() string {
	return string(cmr)
}
