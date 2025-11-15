package db

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/pkg/errors"
	"gorm.io/gorm"
)

// ChatSessionRepository is the GORM implementation of the chat session repository
type ChatSessionRepository struct {
	db *gorm.DB
}

// NewChatSessionRepository creates a new chat session repository using GORM
func NewChatSessionRepository(db *gorm.DB) repository.ChatSessionRepository {
	return &ChatSessionRepository{
		db: db,
	}
}

// GetByID implements repository.ChatSessionRepository
func (r *ChatSessionRepository) GetByID(ctx context.Context, id string) (*entity.ChatSession, error) {
	var session entity.ChatSession
	err := r.db.WithContext(ctx).Where("id = ?", id).First(&session).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("Chat session")
		}
		return nil, errors.NewDatabaseError("Failed to get chat session by ID").WithError(err)
	}
	return &session, nil
}

// GetByUserID implements repository.ChatSessionRepository
func (r *ChatSessionRepository) GetByUserID(ctx context.Context, userID string, limit, offset int) ([]*entity.ChatSession, error) {
	var sessions []*entity.ChatSession
	err := r.db.WithContext(ctx).
		Where("user_id = ?", userID).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&sessions).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get chat sessions by user ID").WithError(err)
	}

	return sessions, nil
}

// GetActiveByUserID implements repository.ChatSessionRepository
func (r *ChatSessionRepository) GetActiveByUserID(ctx context.Context, userID string) ([]*entity.ChatSession, error) {
	var sessions []*entity.ChatSession
	err := r.db.WithContext(ctx).
		Where("user_id = ? AND status = ?", userID, string(entity.ChatSessionStatusOpen)).
		Order("created_at DESC").
		Find(&sessions).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get active chat sessions").WithError(err)
	}

	return sessions, nil
}

// Create implements repository.ChatSessionRepository
func (r *ChatSessionRepository) Create(ctx context.Context, session *entity.ChatSession) (*entity.ChatSession, error) {
	if session.ID == "" {
		session.ID = uuid.New().String()
	}

	err := r.db.WithContext(ctx).Create(session).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to create chat session").WithError(err)
	}

	return session, nil
}

// Update implements repository.ChatSessionRepository
func (r *ChatSessionRepository) Update(ctx context.Context, session *entity.ChatSession) (*entity.ChatSession, error) {
	err := r.db.WithContext(ctx).Save(session).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to update chat session").WithError(err)
	}

	return session, nil
}

// Delete implements repository.ChatSessionRepository
func (r *ChatSessionRepository) Delete(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).Where("id = ?", id).Delete(&entity.ChatSession{}).Error
	if err != nil {
		return errors.NewDatabaseError("Failed to delete chat session").WithError(err)
	}

	return nil
}

// List implements repository.ChatSessionRepository
func (r *ChatSessionRepository) List(ctx context.Context, limit, offset int) ([]*entity.ChatSession, error) {
	var sessions []*entity.ChatSession
	err := r.db.WithContext(ctx).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&sessions).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to list chat sessions").WithError(err)
	}

	return sessions, nil
}

// Count implements repository.ChatSessionRepository
func (r *ChatSessionRepository) Count(ctx context.Context) (int64, error) {
	var count int64
	err := r.db.WithContext(ctx).
		Model(&entity.ChatSession{}).
		Count(&count).Error

	if err != nil {
		return 0, errors.NewDatabaseError("Failed to count chat sessions").WithError(err)
	}

	return count, nil
}

// CloseSession implements repository.ChatSessionRepository
func (r *ChatSessionRepository) CloseSession(ctx context.Context, id string) error {
	now := time.Now()
	err := r.db.WithContext(ctx).
		Model(&entity.ChatSession{}).
		Where("id = ?", id).
		Updates(map[string]interface{}{
			"status":    string(entity.ChatSessionStatusClosed),
			"closed_at": now,
		}).Error

	if err != nil {
		return errors.NewDatabaseError("Failed to close chat session").WithError(err)
	}

	return nil
}

// UpdateTokenUsage implements repository.ChatSessionRepository
func (r *ChatSessionRepository) UpdateTokenUsage(ctx context.Context, id string, tokens int) error {
	err := r.db.WithContext(ctx).
		Model(&entity.ChatSession{}).
		Where("id = ?", id).
		Update("token_usage", gorm.Expr("token_usage + ?", tokens)).Error

	if err != nil {
		return errors.NewDatabaseError("Failed to update token usage").WithError(err)
	}

	return nil
}

// ChatMessageRepository is the GORM implementation of the chat message repository
type ChatMessageRepository struct {
	db *gorm.DB
}

// NewChatMessageRepository creates a new chat message repository using GORM
func NewChatMessageRepository(db *gorm.DB) repository.ChatMessageRepository {
	return &ChatMessageRepository{
		db: db,
	}
}

// GetByID implements repository.ChatMessageRepository
func (r *ChatMessageRepository) GetByID(ctx context.Context, id string) (*entity.ChatMessage, error) {
	var message entity.ChatMessage
	err := r.db.WithContext(ctx).Where("id = ?", id).First(&message).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("Chat message")
		}
		return nil, errors.NewDatabaseError("Failed to get chat message by ID").WithError(err)
	}
	return &message, nil
}

// GetBySessionID implements repository.ChatMessageRepository
func (r *ChatMessageRepository) GetBySessionID(ctx context.Context, sessionID string) ([]*entity.ChatMessage, error) {
	var messages []*entity.ChatMessage
	err := r.db.WithContext(ctx).
		Where("session_id = ?", sessionID).
		Order("sequence ASC").
		Find(&messages).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get messages by session ID").WithError(err)
	}

	return messages, nil
}

// GetBySessionIDPaginated implements repository.ChatMessageRepository
func (r *ChatMessageRepository) GetBySessionIDPaginated(ctx context.Context, sessionID string, limit, offset int) ([]*entity.ChatMessage, error) {
	var messages []*entity.ChatMessage
	err := r.db.WithContext(ctx).
		Where("session_id = ?", sessionID).
		Order("sequence ASC").
		Limit(limit).
		Offset(offset).
		Find(&messages).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get paginated messages").WithError(err)
	}

	return messages, nil
}

// Create implements repository.ChatMessageRepository
func (r *ChatMessageRepository) Create(ctx context.Context, message *entity.ChatMessage) (*entity.ChatMessage, error) {
	if message.ID == "" {
		message.ID = uuid.New().String()
	}

	err := r.db.WithContext(ctx).Create(message).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to create chat message").WithError(err)
	}

	return message, nil
}

// CreateBatch implements repository.ChatMessageRepository
func (r *ChatMessageRepository) CreateBatch(ctx context.Context, messages []*entity.ChatMessage) ([]*entity.ChatMessage, error) {
	for i := range messages {
		if messages[i].ID == "" {
			messages[i].ID = uuid.New().String()
		}
	}

	err := r.db.WithContext(ctx).Create(&messages).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to create messages in batch").WithError(err)
	}

	return messages, nil
}

// Delete implements repository.ChatMessageRepository
func (r *ChatMessageRepository) Delete(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).Where("id = ?", id).Delete(&entity.ChatMessage{}).Error
	if err != nil {
		return errors.NewDatabaseError("Failed to delete chat message").WithError(err)
	}

	return nil
}

// DeleteBySessionID implements repository.ChatMessageRepository
func (r *ChatMessageRepository) DeleteBySessionID(ctx context.Context, sessionID string) error {
	err := r.db.WithContext(ctx).Where("session_id = ?", sessionID).Delete(&entity.ChatMessage{}).Error
	if err != nil {
		return errors.NewDatabaseError("Failed to delete messages by session ID").WithError(err)
	}

	return nil
}

// CountBySessionID implements repository.ChatMessageRepository
func (r *ChatMessageRepository) CountBySessionID(ctx context.Context, sessionID string) (int64, error) {
	var count int64
	err := r.db.WithContext(ctx).
		Model(&entity.ChatMessage{}).
		Where("session_id = ?", sessionID).
		Count(&count).Error

	if err != nil {
		return 0, errors.NewDatabaseError("Failed to count messages").WithError(err)
	}

	return count, nil
}

// GetNextSequence implements repository.ChatMessageRepository
func (r *ChatMessageRepository) GetNextSequence(ctx context.Context, sessionID string) (int, error) {
	var maxSequence struct {
		Max int
	}

	err := r.db.WithContext(ctx).
		Model(&entity.ChatMessage{}).
		Where("session_id = ?", sessionID).
		Select("COALESCE(MAX(sequence), -1) as max").
		Scan(&maxSequence).Error

	if err != nil {
		return 0, errors.NewDatabaseError("Failed to get next sequence").WithError(err)
	}

	return maxSequence.Max + 1, nil
}
