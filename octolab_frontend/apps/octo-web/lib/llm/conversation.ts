/**
 * Conversation Context Manager
 * Handles multi-turn chat context and message history
 */

import type { Message, ConversationContext } from "./types";

const MAX_HISTORY_LENGTH = 50;
const MAX_CONTEXT_TOKENS_ESTIMATE = 4000; // Rough estimate for context window management

/**
 * In-memory conversation store
 * In production, this should be persisted to database/Redis
 */
const conversationStore = new Map<string, ConversationContext>();

export class ConversationManager {
  /**
   * Create a new conversation
   */
  static create(userId: string, metadata?: Record<string, unknown>): ConversationContext {
    const id = `conv_${userId}_${Date.now()}`;
    const conversation: ConversationContext = {
      id,
      messages: [],
      metadata,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    conversationStore.set(id, conversation);
    return conversation;
  }

  /**
   * Get an existing conversation or create a new one
   */
  static getOrCreate(
    conversationId: string | null,
    userId: string,
    metadata?: Record<string, unknown>
  ): ConversationContext {
    if (conversationId) {
      const existing = conversationStore.get(conversationId);
      if (existing) {
        return existing;
      }
    }
    return this.create(userId, metadata);
  }

  /**
   * Get a conversation by ID
   */
  static get(conversationId: string): ConversationContext | null {
    return conversationStore.get(conversationId) ?? null;
  }

  /**
   * Add a message to the conversation
   */
  static addMessage(conversationId: string, message: Message): void {
    const conversation = conversationStore.get(conversationId);
    if (!conversation) {
      throw new Error(`Conversation not found: ${conversationId}`);
    }

    conversation.messages.push(message);
    conversation.updatedAt = new Date();

    // Trim history if too long
    if (conversation.messages.length > MAX_HISTORY_LENGTH) {
      // Keep system message if present, then most recent messages
      const systemMessages = conversation.messages.filter((m) => m.role === "system");
      const otherMessages = conversation.messages.filter((m) => m.role !== "system");
      conversation.messages = [
        ...systemMessages,
        ...otherMessages.slice(-MAX_HISTORY_LENGTH + systemMessages.length),
      ];
    }
  }

  /**
   * Get messages formatted for LLM request
   * Optionally includes a system prompt
   */
  static getMessagesForLLM(
    conversationId: string,
    systemPrompt?: string
  ): Message[] {
    const conversation = conversationStore.get(conversationId);
    if (!conversation) {
      throw new Error(`Conversation not found: ${conversationId}`);
    }

    const messages: Message[] = [];

    // Add system prompt if provided
    if (systemPrompt) {
      messages.push({ role: "system", content: systemPrompt });
    }

    // Add conversation history
    messages.push(...conversation.messages);

    return this.trimToContextLimit(messages);
  }

  /**
   * Trim messages to fit within estimated context limit
   * Keeps system prompt and most recent messages
   */
  private static trimToContextLimit(messages: Message[]): Message[] {
    let totalTokensEstimate = 0;
    const result: Message[] = [];

    // Always include system messages
    const systemMessages = messages.filter((m) => m.role === "system");
    const otherMessages = messages.filter((m) => m.role !== "system");

    for (const msg of systemMessages) {
      const tokenEstimate = Math.ceil(msg.content.length / 4);
      totalTokensEstimate += tokenEstimate;
      result.push(msg);
    }

    // Add other messages from most recent, respecting token limit
    const reversedOther = [...otherMessages].reverse();
    const messagesToAdd: Message[] = [];

    for (const msg of reversedOther) {
      const tokenEstimate = Math.ceil(msg.content.length / 4);
      if (totalTokensEstimate + tokenEstimate > MAX_CONTEXT_TOKENS_ESTIMATE) {
        break;
      }
      totalTokensEstimate += tokenEstimate;
      messagesToAdd.unshift(msg);
    }

    result.push(...messagesToAdd);
    return result;
  }

  /**
   * Clear conversation history
   */
  static clear(conversationId: string): void {
    const conversation = conversationStore.get(conversationId);
    if (conversation) {
      conversation.messages = [];
      conversation.updatedAt = new Date();
    }
  }

  /**
   * Delete a conversation
   */
  static delete(conversationId: string): boolean {
    return conversationStore.delete(conversationId);
  }

  /**
   * Get all conversations for a user (for cleanup/admin)
   */
  static getByUser(userId: string): ConversationContext[] {
    const prefix = `conv_${userId}_`;
    const results: ConversationContext[] = [];
    for (const [id, conv] of conversationStore) {
      if (id.startsWith(prefix)) {
        results.push(conv);
      }
    }
    return results;
  }

  /**
   * Cleanup old conversations
   */
  static cleanup(maxAgeMs: number = 24 * 60 * 60 * 1000): number {
    const cutoff = Date.now() - maxAgeMs;
    let deleted = 0;

    for (const [id, conv] of conversationStore) {
      if (conv.updatedAt.getTime() < cutoff) {
        conversationStore.delete(id);
        deleted++;
      }
    }

    return deleted;
  }
}

/**
 * Format a recipe tool call result for display
 */
export interface FormattedRecipeResult {
  action: "recipe" | "clarify" | "chat";
  message: string;
  recipe?: {
    name: string;
    description: string;
    software: string;
    versionConstraint?: string;
    exploitFamily?: string;
    confidence: number;
  };
  suggestions?: string[];
  clarifyOptions?: Array<{ label: string; description: string }>;
}

export function formatToolCallResult(
  toolName: string,
  args: Record<string, unknown>
): FormattedRecipeResult {
  if (toolName === "create_recipe") {
    return {
      action: "recipe",
      message: `I've identified this as a ${args.exploit_family ?? "security"} scenario. Here's the lab configuration:`,
      recipe: {
        name: args.name as string,
        description: args.description as string,
        software: args.software as string,
        versionConstraint: args.version_constraint as string | undefined,
        exploitFamily: args.exploit_family as string | undefined,
        confidence: (args.confidence as number) ?? 0.8,
      },
      suggestions: args.suggestions as string[] | undefined,
    };
  }

  if (toolName === "clarify_intent") {
    return {
      action: "clarify",
      message: args.message as string,
      clarifyOptions: args.options as Array<{ label: string; description: string }>,
      suggestions: (args.options as Array<{ label: string }>)?.map((o) => o.label),
    };
  }

  return {
    action: "chat",
    message: String(args.message ?? args.content ?? ""),
  };
}
