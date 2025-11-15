package usecase

import (
	"context"
	"encoding/json"

	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/internal/infrastructure/services"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/llm"
	"github.com/zerozero/apps/api/pkg/logger"
	"github.com/zerozero/apps/api/pkg/prompts"
)

// ChatUseCase handles chat session business logic
type ChatUseCase interface {
	// CreateSession creates a new chat session
	CreateSession(ctx context.Context, userID string, projectID *string, model string) (*entity.ChatSession, error)

	// GetSession retrieves a chat session by ID
	GetSession(ctx context.Context, sessionID string) (*entity.ChatSession, error)

	// GetSessionWithMessages retrieves a session with its messages
	GetSessionWithMessages(ctx context.Context, sessionID string) (*ChatSessionWithMessages, error)

	// SendMessage sends a message and gets LLM response
	SendMessage(ctx context.Context, sessionID string, userMessage string) (*ChatMessagePair, error)

	// StreamMessage sends a message and streams LLM response
	StreamMessage(ctx context.Context, sessionID string, userMessage string) (<-chan llm.StreamDelta, <-chan error, error)

	// FinalizeSession closes the session and extracts intent
	FinalizeSession(ctx context.Context, sessionID string) (*entity.Intent, error)

	// GetUserSessions retrieves all sessions for a user
	GetUserSessions(ctx context.Context, userID string, limit, offset int) ([]*entity.ChatSession, error)

	// GetActiveSessions retrieves active sessions for a user
	GetActiveSessions(ctx context.Context, userID string) ([]*entity.ChatSession, error)

	// CloseSession manually closes a session without finalizing
	CloseSession(ctx context.Context, sessionID string) error

	// DeleteSession deletes a session and its messages
	DeleteSession(ctx context.Context, sessionID string) error
}

// chatUseCase is the concrete implementation
type chatUseCase struct {
	sessionRepo repository.ChatSessionRepository
	messageRepo repository.ChatMessageRepository
	intentRepo  repository.IntentRepository
	llmService  services.LLMService
	log         logger.Logger
}

// NewChatUseCase creates a new chat use case
func NewChatUseCase(
	sessionRepo repository.ChatSessionRepository,
	messageRepo repository.ChatMessageRepository,
	intentRepo repository.IntentRepository,
	llmService services.LLMService,
	log logger.Logger,
) ChatUseCase {
	return &chatUseCase{
		sessionRepo: sessionRepo,
		messageRepo: messageRepo,
		intentRepo:  intentRepo,
		llmService:  llmService,
		log:         log,
	}
}

// ChatSessionWithMessages contains a session and its messages
type ChatSessionWithMessages struct {
	Session  *entity.ChatSession   `json:"session"`
	Messages []*entity.ChatMessage `json:"messages"`
}

// ChatMessagePair contains user message and assistant response
type ChatMessagePair struct {
	UserMessage      *entity.ChatMessage `json:"user_message"`
	AssistantMessage *entity.ChatMessage `json:"assistant_message"`
	TokensUsed       int                 `json:"tokens_used"`
}

// CreateSession implements ChatUseCase
func (uc *chatUseCase) CreateSession(ctx context.Context, userID string, projectID *string, model string) (*entity.ChatSession, error) {
	uc.log.Info("Creating new chat session", logger.String("user_id", userID))

	// Set default model if not provided
	if model == "" {
		model = "gpt-4o"
	}

	session := &entity.ChatSession{
		UserID:             userID,
		ProjectID:          projectID,
		Status:             entity.ChatSessionStatusOpen,
		LLMModel:           model,
		TokenUsage:         0,
		MaxTokens:          50000,
		MaxDurationMinutes: 30,
	}

	// Validate session
	if err := session.Validate(); err != nil {
		return nil, err
	}

	// Create session
	createdSession, err := uc.sessionRepo.Create(ctx, session)
	if err != nil {
		uc.log.Error("Failed to create chat session", logger.Error(err))
		return nil, errors.NewInternal("Failed to create chat session").WithError(err)
	}

	// Add initial system message
	systemMessage := &entity.ChatMessage{
		SessionID: createdSession.ID,
		Role:      entity.ChatMessageRoleSystem,
		Content:   prompts.ChatSystemPrompt,
		Sequence:  0,
		Tokens:    uc.llmService.EstimateTokens(prompts.ChatSystemPrompt),
	}

	_, err = uc.messageRepo.Create(ctx, systemMessage)
	if err != nil {
		uc.log.Warn("Failed to create system message", logger.Error(err))
		// Don't fail session creation if system message fails
	}

	uc.log.Info("Chat session created", logger.String("session_id", createdSession.ID))
	return createdSession, nil
}

// GetSession implements ChatUseCase
func (uc *chatUseCase) GetSession(ctx context.Context, sessionID string) (*entity.ChatSession, error) {
	session, err := uc.sessionRepo.GetByID(ctx, sessionID)
	if err != nil {
		return nil, err
	}

	return session, nil
}

// GetSessionWithMessages implements ChatUseCase
func (uc *chatUseCase) GetSessionWithMessages(ctx context.Context, sessionID string) (*ChatSessionWithMessages, error) {
	// Get session
	session, err := uc.sessionRepo.GetByID(ctx, sessionID)
	if err != nil {
		return nil, err
	}

	// Get messages
	messages, err := uc.messageRepo.GetBySessionID(ctx, sessionID)
	if err != nil {
		uc.log.Error("Failed to get messages", logger.Error(err))
		return nil, errors.NewInternal("Failed to get messages").WithError(err)
	}

	return &ChatSessionWithMessages{
		Session:  session,
		Messages: messages,
	}, nil
}

// SendMessage implements ChatUseCase
func (uc *chatUseCase) SendMessage(ctx context.Context, sessionID string, userMessage string) (*ChatMessagePair, error) {
	uc.log.Info("Sending message", logger.String("session_id", sessionID))

	// Get session
	session, err := uc.sessionRepo.GetByID(ctx, sessionID)
	if err != nil {
		return nil, err
	}

	// Check if session is open
	if !session.IsOpen() {
		return nil, errors.NewValidation("session_status: Session is not open")
	}

	// Check budget
	if session.ShouldAutoClose() {
		uc.log.Warn("Session exceeded budget, auto-closing", logger.String("session_id", sessionID))
		_ = uc.sessionRepo.CloseSession(ctx, sessionID)
		return nil, errors.NewValidation("session_budget: Session has exceeded budget or duration limit")
	}

	// Get conversation history
	messages, err := uc.messageRepo.GetBySessionID(ctx, sessionID)
	if err != nil {
		return nil, errors.NewInternal("Failed to get conversation history").WithError(err)
	}

	// Get next sequence number
	nextSeq, err := uc.messageRepo.GetNextSequence(ctx, sessionID)
	if err != nil {
		return nil, errors.NewInternal("Failed to get next sequence").WithError(err)
	}

	// Create user message
	userMsgEntity := &entity.ChatMessage{
		SessionID: sessionID,
		Role:      entity.ChatMessageRoleUser,
		Content:   userMessage,
		Sequence:  nextSeq,
		Tokens:    uc.llmService.EstimateTokens(userMessage),
	}

	savedUserMsg, err := uc.messageRepo.Create(ctx, userMsgEntity)
	if err != nil {
		return nil, errors.NewInternal("Failed to save user message").WithError(err)
	}

	// Convert to LLM messages
	llmMessages := uc.convertToLLMMessages(messages)
	llmMessages = append(llmMessages, llm.Message{
		Role:    llm.RoleUser,
		Content: userMessage,
	})

	// Call LLM
	request := &llm.CompletionRequest{
		Model:       session.LLMModel,
		Messages:    llmMessages,
		Temperature: 0.7,
		MaxTokens:   2000,
	}

	response, err := uc.llmService.Chat(ctx, request)
	if err != nil {
		uc.log.Error("Failed to get LLM response", logger.Error(err))
		return nil, errors.NewInternal("Failed to get AI response").WithError(err)
	}

	if len(response.Choices) == 0 {
		return nil, errors.NewInternal("No response from AI")
	}

	assistantContent := response.Choices[0].Message.Content

	// Create assistant message
	assistantMsgEntity := &entity.ChatMessage{
		SessionID: sessionID,
		Role:      entity.ChatMessageRoleAssistant,
		Content:   assistantContent,
		Sequence:  nextSeq + 1,
		Tokens:    response.Usage.CompletionTokens,
	}

	savedAssistantMsg, err := uc.messageRepo.Create(ctx, assistantMsgEntity)
	if err != nil {
		return nil, errors.NewInternal("Failed to save assistant message").WithError(err)
	}

	// Update token usage
	tokensUsed := response.Usage.TotalTokens
	err = uc.sessionRepo.UpdateTokenUsage(ctx, sessionID, tokensUsed)
	if err != nil {
		uc.log.Warn("Failed to update token usage", logger.Error(err))
	}

	uc.log.Info("Message sent and response received",
		logger.String("session_id", sessionID),
		logger.Int("tokens_used", tokensUsed))

	return &ChatMessagePair{
		UserMessage:      savedUserMsg,
		AssistantMessage: savedAssistantMsg,
		TokensUsed:       tokensUsed,
	}, nil
}

// StreamMessage implements ChatUseCase
func (uc *chatUseCase) StreamMessage(ctx context.Context, sessionID string, userMessage string) (<-chan llm.StreamDelta, <-chan error, error) {
	uc.log.Info("Starting streaming message", logger.String("session_id", sessionID))

	// Get session
	session, err := uc.sessionRepo.GetByID(ctx, sessionID)
	if err != nil {
		return nil, nil, err
	}

	// Check if session is open
	if !session.IsOpen() {
		return nil, nil, errors.NewValidation("session_status: Session is not open")
	}

	// Check budget
	if session.ShouldAutoClose() {
		return nil, nil, errors.NewValidation("session_budget: Session has exceeded budget or duration limit")
	}

	// Get conversation history
	messages, err := uc.messageRepo.GetBySessionID(ctx, sessionID)
	if err != nil {
		return nil, nil, errors.NewInternal("Failed to get conversation history").WithError(err)
	}

	// Save user message
	nextSeq, _ := uc.messageRepo.GetNextSequence(ctx, sessionID)
	userMsgEntity := &entity.ChatMessage{
		SessionID: sessionID,
		Role:      entity.ChatMessageRoleUser,
		Content:   userMessage,
		Sequence:  nextSeq,
		Tokens:    uc.llmService.EstimateTokens(userMessage),
	}

	_, err = uc.messageRepo.Create(ctx, userMsgEntity)
	if err != nil {
		return nil, nil, errors.NewInternal("Failed to save user message").WithError(err)
	}

	// Convert to LLM messages
	llmMessages := uc.convertToLLMMessages(messages)
	llmMessages = append(llmMessages, llm.Message{
		Role:    llm.RoleUser,
		Content: userMessage,
	})

	// Stream LLM response
	request := &llm.CompletionRequest{
		Model:       session.LLMModel,
		Messages:    llmMessages,
		Temperature: 0.7,
		MaxTokens:   2000,
		Stream:      true,
	}

	deltaChan, errorChan := uc.llmService.StreamChat(ctx, request)

	return deltaChan, errorChan, nil
}

// FinalizeSession implements ChatUseCase
func (uc *chatUseCase) FinalizeSession(ctx context.Context, sessionID string) (*entity.Intent, error) {
	uc.log.Info("Finalizing chat session", logger.String("session_id", sessionID))

	// Get session
	session, err := uc.sessionRepo.GetByID(ctx, sessionID)
	if err != nil {
		return nil, err
	}

	// Check if session can be finalized
	if session.IsClosed() {
		return nil, errors.NewValidation("session_status: Session is already closed")
	}

	// Update status to finalizing
	session.Status = entity.ChatSessionStatusFinalizing
	_, err = uc.sessionRepo.Update(ctx, session)
	if err != nil {
		return nil, errors.NewInternal("Failed to update session status").WithError(err)
	}

	// Get conversation history
	messages, err := uc.messageRepo.GetBySessionID(ctx, sessionID)
	if err != nil {
		return nil, errors.NewInternal("Failed to get conversation history").WithError(err)
	}

	// Convert to LLM messages (exclude system message)
	llmMessages := []llm.Message{}
	for _, msg := range messages {
		if msg.Role != entity.ChatMessageRoleSystem {
			llmMessages = append(llmMessages, llm.Message{
				Role:    llm.Role(msg.Role),
				Content: msg.Content,
			})
		}
	}

	// Extract intent
	intentRequest := &llm.IntentExtractionRequest{
		ConversationHistory: llmMessages,
		Model:               session.LLMModel,
		Temperature:         0.3,
	}

	intentResponse, err := uc.llmService.ExtractIntent(ctx, intentRequest)
	if err != nil {
		uc.log.Error("Failed to extract intent", logger.Error(err))
		return nil, errors.NewInternal("Failed to extract intent").WithError(err)
	}

	// Create intent payload
	payloadJSON, err := json.Marshal(intentResponse.Intent)
	if err != nil {
		return nil, errors.NewInternal("Failed to marshal intent payload").WithError(err)
	}

	// Create intent entity
	intent := &entity.Intent{
		SessionID:  sessionID,
		Payload:    json.RawMessage(payloadJSON),
		Confidence: intentResponse.Confidence,
		Status:     entity.IntentStatusDraft,
	}

	// Validate intent
	if err := intent.Validate(); err != nil {
		return nil, err
	}

	// Save intent
	savedIntent, err := uc.intentRepo.Create(ctx, intent)
	if err != nil {
		uc.log.Error("Failed to save intent", logger.Error(err))
		return nil, errors.NewInternal("Failed to save intent").WithError(err)
	}

	// Close session
	err = uc.sessionRepo.CloseSession(ctx, sessionID)
	if err != nil {
		uc.log.Warn("Failed to close session", logger.Error(err))
	}

	uc.log.Info("Session finalized",
		logger.String("session_id", sessionID),
		logger.String("intent_id", savedIntent.ID),
		logger.Any("confidence", savedIntent.Confidence))

	return savedIntent, nil
}

// GetUserSessions implements ChatUseCase
func (uc *chatUseCase) GetUserSessions(ctx context.Context, userID string, limit, offset int) ([]*entity.ChatSession, error) {
	return uc.sessionRepo.GetByUserID(ctx, userID, limit, offset)
}

// GetActiveSessions implements ChatUseCase
func (uc *chatUseCase) GetActiveSessions(ctx context.Context, userID string) ([]*entity.ChatSession, error) {
	return uc.sessionRepo.GetActiveByUserID(ctx, userID)
}

// CloseSession implements ChatUseCase
func (uc *chatUseCase) CloseSession(ctx context.Context, sessionID string) error {
	return uc.sessionRepo.CloseSession(ctx, sessionID)
}

// DeleteSession implements ChatUseCase
func (uc *chatUseCase) DeleteSession(ctx context.Context, sessionID string) error {
	uc.log.Info("Deleting chat session", logger.String("session_id", sessionID))
	return uc.sessionRepo.Delete(ctx, sessionID)
}

// convertToLLMMessages converts entity messages to LLM messages
func (uc *chatUseCase) convertToLLMMessages(messages []*entity.ChatMessage) []llm.Message {
	llmMessages := make([]llm.Message, 0, len(messages))
	for _, msg := range messages {
		llmMessages = append(llmMessages, llm.Message{
			Role:    llm.Role(msg.Role),
			Content: msg.Content,
		})
	}
	return llmMessages
}
