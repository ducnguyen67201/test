/**
 * Recipe types for OctoLab CVE rehearsal platform.
 * Recipes define vulnerability templates and lab configurations.
 */

export interface Recipe {
  id: string;
  name: string;
  description: string | null;
  software: string;
  version_constraint: string | null;
  exploit_family: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RecipeCreate {
  name: string;
  description?: string | null;
  software: string;
  version_constraint?: string | null;
  exploit_family?: string | null;
  is_active?: boolean;
}

/**
 * Lab status lifecycle
 */
export type LabStatus =
  | "requested"
  | "provisioning"
  | "ready"
  | "ending"
  | "finished"
  | "failed";

export interface Lab {
  id: string;
  owner_id: string;
  recipe_id: string;
  status: LabStatus;
  connection_url: string | null;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Chat message with recipe context
 */
export interface ChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
  timestamp: string;
  suggestions?: string[];
  recipe?: RecipeCreate | null;
  isGenerating?: boolean;
}

/**
 * LLM response containing parsed recipe from user intent
 */
export interface LLMRecipeResponse {
  message: string;
  recipe: RecipeCreate | null;
  confidence: number;
  suggestions: string[];
}

/**
 * Supported exploit families
 */
export const EXPLOIT_FAMILIES = [
  "path_traversal",
  "rce",
  "sql_injection",
  "xss",
  "ssrf",
  "deserialization",
  "buffer_overflow",
  "privilege_escalation",
  "authentication_bypass",
  "information_disclosure",
] as const;

export type ExploitFamily = (typeof EXPLOIT_FAMILIES)[number];
