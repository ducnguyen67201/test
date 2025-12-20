/**
 * OpenAI LLM Provider
 */

import type {
  Message,
  LLMResponse,
  LLMRequestOptions,
  ToolDefinition,
  ToolCall,
} from "../types";
import { BaseLLMProvider, LLMProviderError } from "./base";

interface OpenAIMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  name?: string;
  tool_call_id?: string;
  tool_calls?: Array<{
    id: string;
    type: "function";
    function: {
      name: string;
      arguments: string;
    };
  }>;
}

interface OpenAITool {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

interface OpenAIResponse {
  id: string;
  choices: Array<{
    index: number;
    message: OpenAIMessage;
    finish_reason: "stop" | "tool_calls" | "length" | "content_filter";
  }>;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  model: string;
}

export class OpenAIProvider extends BaseLLMProvider {
  get name(): string {
    return "openai";
  }

  async isAvailable(): Promise<boolean> {
    if (!this.config.apiKey) {
      return false;
    }

    try {
      const response = await fetch(
        `${this.config.baseUrl ?? "https://api.openai.com"}/v1/models`,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${this.config.apiKey}`,
          },
        }
      );
      return response.ok;
    } catch {
      return false;
    }
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

    const openaiMessages = this.convertMessages(messages);
    const model = options?.model ?? this.config.defaultModel;

    const requestBody: Record<string, unknown> = {
      model,
      messages: openaiMessages,
      temperature: options?.temperature ?? 0.7,
      max_tokens: options?.maxTokens ?? 2048,
    };

    if (options?.tools?.length) {
      requestBody.tools = this.convertTools(options.tools);
      requestBody.tool_choice = options.toolChoice ?? "auto";
    }

    console.log(`[OpenAI] Request to model=${model}, messages=${messages.length}, tools=${options?.tools?.length ?? 0}`);
    const startTime = Date.now();

    try {
      const response = await fetch(
        `${this.config.baseUrl ?? "https://api.openai.com"}/v1/chat/completions`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${this.config.apiKey}`,
          },
          body: JSON.stringify(requestBody),
        }
      );

      if (!response.ok) {
        const error = await response.text();
        console.error(`[OpenAI] API error ${response.status}: ${error.substring(0, 200)}`);
        const isRetryable = response.status >= 500 || response.status === 429;
        throw new LLMProviderError(
          this.name,
          new Error(`API error ${response.status}: ${error}`),
          isRetryable
        );
      }

      const data = (await response.json()) as OpenAIResponse;
      const elapsed = Date.now() - startTime;

      console.log(`[OpenAI] Response in ${elapsed}ms: tokens=${data.usage.total_tokens} (prompt=${data.usage.prompt_tokens}, completion=${data.usage.completion_tokens})`);

      if (data.choices[0]?.message?.tool_calls?.length) {
        const toolNames = data.choices[0].message.tool_calls.map(tc => tc.function.name);
        console.log(`[OpenAI] Tool calls: ${toolNames.join(', ')}`);
      }

      return this.parseResponse(data, model);
    } catch (error) {
      if (error instanceof LLMProviderError) {
        throw error;
      }
      console.error(`[OpenAI] Request failed after ${Date.now() - startTime}ms:`, error);
      throw new LLMProviderError(
        this.name,
        error instanceof Error ? error : new Error(String(error)),
        true
      );
    }
  }

  private convertMessages(messages: Message[]): OpenAIMessage[] {
    return messages.map((msg) => {
      const openaiMsg: OpenAIMessage = {
        role: msg.role,
        content: msg.content,
      };

      if (msg.name) {
        openaiMsg.name = msg.name;
      }
      if (msg.toolCallId) {
        openaiMsg.tool_call_id = msg.toolCallId;
      }

      return openaiMsg;
    });
  }

  private convertTools(tools: ToolDefinition[]): OpenAITool[] {
    return tools.map((tool) => ({
      type: "function",
      function: {
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
      },
    }));
  }

  private parseResponse(data: OpenAIResponse, model: string): LLMResponse {
    const choice = data.choices[0];
    const message = choice?.message;

    let toolCalls: ToolCall[] | undefined;
    if (message?.tool_calls?.length) {
      toolCalls = message.tool_calls.map((tc) => ({
        id: tc.id,
        name: tc.function.name,
        arguments: JSON.parse(tc.function.arguments) as Record<string, unknown>,
      }));
    }

    let finishReason: LLMResponse["finishReason"];
    switch (choice?.finish_reason) {
      case "tool_calls":
        finishReason = "tool_calls";
        break;
      case "length":
        finishReason = "length";
        break;
      case "content_filter":
        finishReason = "error";
        break;
      default:
        finishReason = "stop";
    }

    return {
      content: message?.content ?? "",
      toolCalls,
      finishReason,
      provider: "openai",
      model,
      usage: {
        promptTokens: data.usage.prompt_tokens,
        completionTokens: data.usage.completion_tokens,
        totalTokens: data.usage.total_tokens,
      },
    };
  }
}
