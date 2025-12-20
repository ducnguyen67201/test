/**
 * Base LLM Provider Interface
 */

import type {
  Message,
  LLMResponse,
  LLMRequestOptions,
  ProviderConfig,
} from "../types";

export abstract class BaseLLMProvider {
  protected config: ProviderConfig;

  constructor(config: ProviderConfig) {
    this.config = config;
  }

  abstract get name(): string;

  abstract chat(
    messages: Message[],
    options?: LLMRequestOptions
  ): Promise<LLMResponse>;

  abstract isAvailable(): Promise<boolean>;

  get priority(): number {
    return this.config.priority;
  }

  get enabled(): boolean {
    return this.config.enabled;
  }

  get defaultModel(): string {
    return this.config.defaultModel;
  }
}

export class LLMProviderError extends Error {
  constructor(
    public provider: string,
    public originalError: Error,
    public retryable: boolean = true
  ) {
    super(`[${provider}] ${originalError.message}`);
    this.name = "LLMProviderError";
  }
}
