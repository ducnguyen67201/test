/**
 * LLM Manager - Centralized LLM orchestration with provider fallback
 */

import type {
  Message,
  LLMResponse,
  LLMRequestOptions,
  LLMManagerConfig,
  ProviderConfig,
  LLMProvider,
} from "./types";
import { BaseLLMProvider, LLMProviderError } from "./providers/base";
import { OpenAIProvider } from "./providers/openai";
import { AnthropicProvider } from "./providers/anthropic";
import { MockLLMProvider } from "./providers/mock";

const DEFAULT_CONFIG: LLMManagerConfig = {
  providers: [
    {
      provider: "openai",
      apiKey: process.env.OPENAI_API_KEY,
      defaultModel: "gpt-4o-mini", // Primary: cheapest with good function calling
      enabled: !!process.env.OPENAI_API_KEY,
      priority: 1,
    },
    {
      provider: "anthropic",
      apiKey: process.env.ANTHROPIC_API_KEY,
      defaultModel: "claude-3-5-haiku-20241022", // Fallback: Claude Haiku
      enabled: !!process.env.ANTHROPIC_API_KEY,
      priority: 2,
    },
    {
      provider: "mock",
      defaultModel: "mock-gpt-4",
      enabled: true, // Always available as fallback
      priority: 99,
    },
  ],
  maxRetries: 2,
  retryDelayMs: 1000,
};

export class LLMManager {
  private providers: Map<LLMProvider, BaseLLMProvider> = new Map();
  private config: LLMManagerConfig;
  private sortedProviders: BaseLLMProvider[] = [];

  constructor(config?: Partial<LLMManagerConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.initializeProviders();
  }

  private initializeProviders(): void {
    for (const providerConfig of this.config.providers) {
      if (!providerConfig.enabled) continue;

      const provider = this.createProvider(providerConfig);
      if (provider) {
        this.providers.set(providerConfig.provider, provider);
      }
    }

    // Sort providers by priority (lower = higher priority)
    this.sortedProviders = Array.from(this.providers.values()).sort(
      (a, b) => a.priority - b.priority
    );
  }

  private createProvider(config: ProviderConfig): BaseLLMProvider | null {
    switch (config.provider) {
      case "openai":
        return new OpenAIProvider(config);
      case "anthropic":
        return new AnthropicProvider(config);
      case "mock":
        return new MockLLMProvider(config);
      default:
        console.warn(`Unknown provider: ${config.provider}`);
        return null;
    }
  }

  /**
   * Send a chat request with automatic provider fallback
   */
  async chat(
    messages: Message[],
    options?: LLMRequestOptions & { preferredProvider?: LLMProvider }
  ): Promise<LLMResponse> {
    const errors: Error[] = [];
    const startTime = Date.now();

    console.log(`[LLM-Manager] Starting chat request with ${messages.length} messages`);
    console.log(`[LLM-Manager] Available providers: ${this.sortedProviders.map(p => p.name).join(', ')}`);

    // If preferred provider specified, try it first
    if (options?.preferredProvider) {
      const preferred = this.providers.get(options.preferredProvider);
      if (preferred?.enabled) {
        try {
          const response = await this.chatWithRetry(preferred, messages, options);
          console.log(`[LLM-Manager] Success with ${options.preferredProvider} in ${Date.now() - startTime}ms`);
          return response;
        } catch (error) {
          errors.push(error instanceof Error ? error : new Error(String(error)));
          console.warn(
            `[LLM-Manager] Preferred provider ${options.preferredProvider} failed, trying fallbacks...`
          );
        }
      }
    }

    // Try providers in priority order
    for (const provider of this.sortedProviders) {
      // Skip if this was already tried as preferred
      if (options?.preferredProvider && provider.name === options.preferredProvider) {
        continue;
      }

      try {
        console.log(`[LLM-Manager] Trying provider: ${provider.name}`);
        const response = await this.chatWithRetry(provider, messages, options);
        console.log(`[LLM-Manager] Success with ${provider.name} in ${Date.now() - startTime}ms`);
        return response;
      } catch (error) {
        errors.push(error instanceof Error ? error : new Error(String(error)));
        console.warn(`[LLM-Manager] Provider ${provider.name} failed, trying next...`);
      }
    }

    // All providers failed
    console.error(`[LLM-Manager] All providers failed after ${Date.now() - startTime}ms`);
    throw new Error(
      `All LLM providers failed:\n${errors.map((e) => e.message).join("\n")}`
    );
  }

  private async chatWithRetry(
    provider: BaseLLMProvider,
    messages: Message[],
    options?: LLMRequestOptions
  ): Promise<LLMResponse> {
    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
      try {
        return await provider.chat(messages, options);
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));

        // Don't retry non-retryable errors
        if (error instanceof LLMProviderError && !error.retryable) {
          throw error;
        }

        // Wait before retry (exponential backoff)
        if (attempt < this.config.maxRetries) {
          const delay = this.config.retryDelayMs * Math.pow(2, attempt);
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
      }
    }

    throw lastError ?? new Error("Unknown error during chat");
  }

  /**
   * Get list of available providers
   */
  getAvailableProviders(): LLMProvider[] {
    return Array.from(this.providers.keys());
  }

  /**
   * Check if a specific provider is available
   */
  async isProviderAvailable(provider: LLMProvider): Promise<boolean> {
    const p = this.providers.get(provider);
    if (!p) return false;
    return p.isAvailable();
  }

  /**
   * Get provider status
   */
  async getStatus(): Promise<
    Array<{
      provider: LLMProvider;
      enabled: boolean;
      available: boolean;
      priority: number;
    }>
  > {
    const status = [];
    for (const [name, provider] of this.providers) {
      status.push({
        provider: name,
        enabled: provider.enabled,
        available: await provider.isAvailable(),
        priority: provider.priority,
      });
    }
    return status.sort((a, b) => a.priority - b.priority);
  }
}

// Singleton instance
let llmManagerInstance: LLMManager | null = null;

export function getLLMManager(): LLMManager {
  if (!llmManagerInstance) {
    llmManagerInstance = new LLMManager();
  }
  return llmManagerInstance;
}

export function resetLLMManager(): void {
  llmManagerInstance = null;
}
