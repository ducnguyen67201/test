package repository

import (
	"context"
	"github.com/zerozero/apps/api/internal/domain/entity"
)

// ChatSessionRepository defines the interface for chat session data access
type ChatSessionRepository interface {
	// GetByID retrieves a chat session by its ID
	GetByID(ctx context.Context, id string) (*entity.ChatSession, error)

	// GetByUserID retrieves all chat sessions for a specific user
	GetByUserID(ctx context.Context, userID string, limit, offset int) ([]*entity.ChatSession, error)

	// GetActiveByUserID retrieves open chat sessions for a user
	GetActiveByUserID(ctx context.Context, userID string) ([]*entity.ChatSession, error)

	// Create creates a new chat session
	Create(ctx context.Context, session *entity.ChatSession) (*entity.ChatSession, error)

	// Update updates an existing chat session
	Update(ctx context.Context, session *entity.ChatSession) (*entity.ChatSession, error)

	// Delete deletes a chat session (and cascades to messages)
	Delete(ctx context.Context, id string) error

	// List lists chat sessions with pagination
	List(ctx context.Context, limit, offset int) ([]*entity.ChatSession, error)

	// Count counts total chat sessions
	Count(ctx context.Context) (int64, error)

	// CloseSession closes a chat session
	CloseSession(ctx context.Context, id string) error

	// UpdateTokenUsage updates the token usage for a session
	UpdateTokenUsage(ctx context.Context, id string, tokens int) error
}

// ChatMessageRepository defines the interface for chat message data access
type ChatMessageRepository interface {
	// GetByID retrieves a message by its ID
	GetByID(ctx context.Context, id string) (*entity.ChatMessage, error)

	// GetBySessionID retrieves all messages for a session, ordered by sequence
	GetBySessionID(ctx context.Context, sessionID string) ([]*entity.ChatMessage, error)

	// GetBySessionIDPaginated retrieves messages for a session with pagination
	GetBySessionIDPaginated(ctx context.Context, sessionID string, limit, offset int) ([]*entity.ChatMessage, error)

	// Create creates a new chat message
	Create(ctx context.Context, message *entity.ChatMessage) (*entity.ChatMessage, error)

	// CreateBatch creates multiple messages in a batch
	CreateBatch(ctx context.Context, messages []*entity.ChatMessage) ([]*entity.ChatMessage, error)

	// Delete deletes a message
	Delete(ctx context.Context, id string) error

	// DeleteBySessionID deletes all messages for a session
	DeleteBySessionID(ctx context.Context, sessionID string) error

	// CountBySessionID counts messages in a session
	CountBySessionID(ctx context.Context, sessionID string) (int64, error)

	// GetNextSequence gets the next sequence number for a session
	GetNextSequence(ctx context.Context, sessionID string) (int, error)
}
