import { z } from "zod";

export const exploitFamilySchema = z.enum([
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
]);

export const recipeCreateSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(5000).optional().nullable(),
  software: z.string().min(1, "Software is required").max(255),
  version_constraint: z.string().max(255).optional().nullable(),
  exploit_family: exploitFamilySchema.optional().nullable(),
  is_active: z.boolean().default(true),
});

export const recipeResponseSchema = recipeCreateSchema.extend({
  id: z.string().uuid(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const chatMessageSchema = z.object({
  content: z.string().min(1, "Message is required").max(10000),
});

export const llmRecipeResponseSchema = z.object({
  message: z.string(),
  recipe: recipeCreateSchema.nullable(),
  confidence: z.number().min(0).max(1),
  suggestions: z.array(z.string()),
});

export type RecipeCreate = z.infer<typeof recipeCreateSchema>;
export type RecipeResponse = z.infer<typeof recipeResponseSchema>;
export type ChatMessage = z.infer<typeof chatMessageSchema>;
export type LLMRecipeResponse = z.infer<typeof llmRecipeResponseSchema>;
