/**
 * Anthropic (Claude) LLM Provider
 */

import type {
  Message,
  LLMResponse,
  LLMRequestOptions,
  ToolDefinition,
  ToolCall,
} from "../types";
import { BaseLLMProvider, LLMProviderError } from "./base";

interface AnthropicMessage {
  role: "user" | "assistant";
  content: string | AnthropicContentBlock[];
}

interface AnthropicContentBlock {
  type: "text" | "tool_use" | "tool_result";
  text?: string;
  id?: string;
  name?: string;
  input?: Record<string, unknown>;
  tool_use_id?: string;
  content?: string;
}

interface AnthropicTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

interface AnthropicResponse {
  id: string;
  type: "message";
  role: "assistant";
  content: AnthropicContentBlock[];
  model: string;
  stop_reason: "end_turn" | "tool_use" | "max_tokens" | "stop_sequence";
  usage: {
    input_tokens: number;
    output_tokens: number;
  };
}

export class AnthropicProvider extends BaseLLMProvider {
  get name(): string {
    return "anthropic";
  }

  async isAvailable(): Promise<boolean> {
    if (!this.config.apiKey) {
      return false;
    }

    // Anthropic doesn't have a simple health check endpoint
    // We'll just verify the API key is set
    return true;
  }

  async chat(
    messages: Message[],
    options?: LLMRequestOptions
  ): Promise<LLMResponse> {
    if (!this.config.apiKey) {
      throw new LLMProviderError(
        this.name,
        new Error("API key not configured"),
        false
      );
    }

    const { systemMessage, anthropicMessages } = this.convertMessages(messages);
    const model = options?.model ?? this.config.defaultModel;

    const requestBody: Record<string, unknown> = {
      model,
      messages: anthropicMessages,
      max_tokens: options?.maxTokens ?? 2048,
    };

    if (systemMessage) {
      requestBody.system = systemMessage;
    }

    if (options?.temperature !== undefined) {
      requestBody.temperature = options.temperature;
    }

    if (options?.tools?.length) {
      requestBody.tools = this.convertTools(options.tools);
      if (options.toolChoice) {
        if (options.toolChoice === "auto") {
          requestBody.tool_choice = { type: "auto" };
        } else if (options.toolChoice === "none") {
          requestBody.tool_choice = { type: "none" };
        } else if (typeof options.toolChoice === "object") {
          requestBody.tool_choice = {
            type: "tool",
            name: options.toolChoice.name,
          };
        }
      }
    }

    try {
      const response = await fetch(
        `${this.config.baseUrl ?? "https://api.anthropic.com"}/v1/messages`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-api-key": this.config.apiKey,
            "anthropic-version": "2023-06-01",
          },
          body: JSON.stringify(requestBody),
        }
      );

      if (!response.ok) {
        const error = await response.text();
        const isRetryable = response.status >= 500 || response.status === 429;
        throw new LLMProviderError(
          this.name,
          new Error(`API error ${response.status}: ${error}`),
          isRetryable
        );
      }

      const data = (await response.json()) as AnthropicResponse;
      return this.parseResponse(data, model);
    } catch (error) {
      if (error instanceof LLMProviderError) {
        throw error;
      }
      throw new LLMProviderError(
        this.name,
        error instanceof Error ? error : new Error(String(error)),
        true
      );
    }
  }

  private convertMessages(messages: Message[]): {
    systemMessage: string | null;
    anthropicMessages: AnthropicMessage[];
  } {
    let systemMessage: string | null = null;
    const anthropicMessages: AnthropicMessage[] = [];

    for (const msg of messages) {
      if (msg.role === "system") {
        systemMessage = msg.content;
        continue;
      }

      if (msg.role === "tool") {
        // Convert tool results to Anthropic format
        const lastMsg = anthropicMessages[anthropicMessages.length - 1];
        if (lastMsg?.role === "user" && Array.isArray(lastMsg.content)) {
          lastMsg.content.push({
            type: "tool_result",
            tool_use_id: msg.toolCallId,
            content: msg.content,
          });
        } else {
          anthropicMessages.push({
            role: "user",
            content: [
              {
                type: "tool_result",
                tool_use_id: msg.toolCallId,
                content: msg.content,
              },
            ],
          });
        }
        continue;
      }

      // Anthropic only supports user and assistant roles
      const role = msg.role === "assistant" ? "assistant" : "user";
      anthropicMessages.push({
        role,
        content: msg.content,
      });
    }

    return { systemMessage, anthropicMessages };
  }

  private convertTools(tools: ToolDefinition[]): AnthropicTool[] {
    return tools.map((tool) => ({
      name: tool.name,
      description: tool.description,
      input_schema: tool.parameters,
    }));
  }

  private parseResponse(data: AnthropicResponse, model: string): LLMResponse {
    let textContent = "";
    const toolCalls: ToolCall[] = [];

    for (const block of data.content) {
      if (block.type === "text" && block.text) {
        textContent += block.text;
      } else if (block.type === "tool_use" && block.id && block.name) {
        toolCalls.push({
          id: block.id,
          name: block.name,
          arguments: block.input ?? {},
        });
      }
    }

    let finishReason: LLMResponse["finishReason"];
    switch (data.stop_reason) {
      case "tool_use":
        finishReason = "tool_calls";
        break;
      case "max_tokens":
        finishReason = "length";
        break;
      default:
        finishReason = "stop";
    }

    return {
      content: textContent,
      toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
      finishReason,
      provider: "anthropic",
      model,
      usage: {
        promptTokens: data.usage.input_tokens,
        completionTokens: data.usage.output_tokens,
        totalTokens: data.usage.input_tokens + data.usage.output_tokens,
      },
    };
  }
}
