/**
 * LLM Types for multi-provider support with fallback
 */

export type LLMProvider = "openai" | "anthropic" | "mock";

export type MessageRole = "system" | "user" | "assistant" | "tool";

export interface Message {
  role: MessageRole;
  content: string;
  name?: string;
  toolCallId?: string;
}

export interface ToolParameter {
  type: string;
  description?: string;
  enum?: string[];
  items?: ToolParameter;
  properties?: Record<string, ToolParameter>;
  required?: string[];
}

export interface ToolDefinition {
  name: string;
  description: string;
  parameters: {
    type: "object";
    properties: Record<string, ToolParameter>;
    required?: string[];
  };
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface LLMResponse {
  content: string;
  toolCalls?: ToolCall[];
  finishReason: "stop" | "tool_calls" | "length" | "error";
  usage?: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
  provider: LLMProvider;
  model: string;
}

export interface LLMRequestOptions {
  model?: string;
  temperature?: number;
  maxTokens?: number;
  tools?: ToolDefinition[];
  toolChoice?: "auto" | "none" | { name: string };
}

export interface ProviderConfig {
  provider: LLMProvider;
  apiKey?: string;
  baseUrl?: string;
  defaultModel: string;
  enabled: boolean;
  priority: number; // Lower = higher priority
}

export interface LLMManagerConfig {
  providers: ProviderConfig[];
  maxRetries: number;
  retryDelayMs: number;
}

/**
 * Conversation context for multi-turn chat
 */
export interface ConversationContext {
  id: string;
  messages: Message[];
  metadata?: Record<string, unknown>;
  createdAt: Date;
  updatedAt: Date;
}

/**
 * Recipe tool result
 */
export interface RecipeToolResult {
  action: "create_recipe" | "clarify" | "chat";
  recipe?: {
    name: string;
    description: string;
    software: string;
    versionConstraint?: string;
    exploitFamily?: string;
    dockerfile?: string;
  };
  message: string;
  suggestions?: string[];
  confidence?: number;
}
