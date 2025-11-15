import { z } from 'zod';

// Chat session status enum
export const ChatSessionStatusSchema = z.enum(['open', 'finalizing', 'closed']);
export type ChatSessionStatus = z.infer<typeof ChatSessionStatusSchema>;

// Chat message role enum
export const ChatMessageRoleSchema = z.enum(['system', 'user', 'assistant']);
export type ChatMessageRole = z.infer<typeof ChatMessageRoleSchema>;

// Chat session schema
export const ChatSessionSchema = z.object({
  id: z.string().uuid(),
  user_id: z.string().uuid(),
  project_id: z.string().uuid().nullable().optional(),
  status: ChatSessionStatusSchema,
  llm_model: z.string(),
  token_usage: z.number().int(),
  max_tokens: z.number().int(),
  max_duration_minutes: z.number().int(),
  created_at: z.string().or(z.date()),
  updated_at: z.string().or(z.date()),
});
export type ChatSession = z.infer<typeof ChatSessionSchema>;

// Chat message schema
export const ChatMessageSchema = z.object({
  id: z.string().uuid(),
  session_id: z.string().uuid(),
  role: ChatMessageRoleSchema,
  content: z.string(),
  sequence: z.number().int(),
  tokens: z.number().int(),
  created_at: z.string().or(z.date()),
});
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

// Create session input
export const CreateChatSessionInputSchema = z.object({
  project_id: z.string().uuid().optional().nullable(),
  model: z.string().optional(),
});
export type CreateChatSessionInput = z.infer<typeof CreateChatSessionInputSchema>;

// Send message input
export const SendMessageInputSchema = z.object({
  session_id: z.string().uuid(),
  message: z.string().min(1, 'Message cannot be empty').max(5000, 'Message is too long'),
});
export type SendMessageInput = z.infer<typeof SendMessageInputSchema>;

// Stream message input
export const StreamMessageInputSchema = z.object({
  session_id: z.string().uuid(),
  message: z.string().min(1, 'Message cannot be empty').max(5000, 'Message is too long'),
});
export type StreamMessageInput = z.infer<typeof StreamMessageInputSchema>;

// Message pair response
export const ChatMessagePairSchema = z.object({
  user_message: ChatMessageSchema,
  assistant_message: ChatMessageSchema,
  tokens_used: z.number().int(),
});
export type ChatMessagePair = z.infer<typeof ChatMessagePairSchema>;

// Session with messages
export const ChatSessionWithMessagesSchema = z.object({
  session: ChatSessionSchema,
  messages: z.array(ChatMessageSchema),
});
export type ChatSessionWithMessages = z.infer<typeof ChatSessionWithMessagesSchema>;

// Intent payload (from chat extraction)
export const IntentPayloadSchema = z.object({
  name: z.string(),
  software: z.string(),
  packages: z.array(
    z.object({
      name: z.string(),
      version: z.string().optional(),
    })
  ),
  os: z.string().optional(),
  cve_data: z
    .object({
      id: z.string(),
      cvss_score: z.number().optional(),
      exploitability_score: z.number().optional(),
    })
    .nullable()
    .optional(),
  compliance_controls: z.array(z.string()).optional(),
  confidence: z.number().min(0).max(1),
});
export type IntentPayload = z.infer<typeof IntentPayloadSchema>;

// Intent status enum
export const IntentStatusSchema = z.enum(['draft', 'approved', 'rejected']);
export type IntentStatus = z.infer<typeof IntentStatusSchema>;

// Intent schema
export const IntentSchema = z.object({
  id: z.string().uuid(),
  session_id: z.string().uuid(),
  payload: z.unknown(), // JSON payload
  confidence: z.number().min(0).max(1),
  status: IntentStatusSchema,
  validator_errors: z.unknown().nullable().optional(),
  created_at: z.string().or(z.date()),
  updated_at: z.string().or(z.date()),
});
export type Intent = z.infer<typeof IntentSchema>;

// Intent validation result
export const IntentValidationResultSchema = z.object({
  passed: z.boolean(),
  errors: z.array(z.string()),
  warnings: z.array(z.string()),
  payload: IntentPayloadSchema.optional(),
});
export type IntentValidationResult = z.infer<typeof IntentValidationResultSchema>;
