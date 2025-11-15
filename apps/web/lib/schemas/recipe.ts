import { z } from 'zod';

// Recipe package schema
export const RecipePackageSchema = z.object({
  name: z.string(),
  version: z.string().optional(),
  manager: z.string().optional(),
});
export type RecipePackage = z.infer<typeof RecipePackageSchema>;

// CVE data schema
export const CVEDataSchema = z.object({
  id: z.string(),
  cvss_score: z.number().optional(),
  exploitability_score: z.number().optional(),
  description: z.string().optional(),
  published_date: z.string().optional(),
});
export type CVEData = z.infer<typeof CVEDataSchema>;

// Recipe schema
export const RecipeSchema = z.object({
  id: z.string().uuid(),
  intent_id: z.string().uuid().nullable().optional(),
  name: z.string(),
  description: z.string(),
  software: z.string(),
  os: z.string(),
  packages: z.array(RecipePackageSchema),
  cve_data: CVEDataSchema.nullable().optional(),
  compliance_controls: z.array(z.string()),
  validation_checks: z.array(z.string()),
  source_urls: z.array(z.string()),
  is_active: z.boolean(),
  created_by: z.string().uuid(),
  created_at: z.string().or(z.date()),
  updated_at: z.string().or(z.date()),
});
export type Recipe = z.infer<typeof RecipeSchema>;

// Create recipe input (manual)
export const CreateRecipeInputSchema = z.object({
  name: z.string().min(1, 'Name is required').max(500, 'Name is too long'),
  description: z.string().max(2000, 'Description is too long').optional(),
  software: z.string().min(1, 'Software is required'),
  version_constraint: z.string().optional(),
  os: z.string().optional(),
  packages: z.array(RecipePackageSchema).optional(),
  network_requirements: z.string().optional(),
  compliance_controls: z.array(z.string()).optional(),
  validation_checks: z.array(z.string()).optional(),
  is_active: z.boolean().optional(),
});
export type CreateRecipeInput = z.infer<typeof CreateRecipeInputSchema>;

// Create recipe from intent
export const CreateRecipeFromIntentInputSchema = z.object({
  intent_id: z.string().uuid(),
});
export type CreateRecipeFromIntentInput = z.infer<typeof CreateRecipeFromIntentInputSchema>;

// Update recipe input
export const UpdateRecipeInputSchema = z.object({
  name: z.string().min(1).max(500).optional(),
  description: z.string().max(2000).optional(),
  network_requirements: z.string().optional(),
  compliance_controls: z.array(z.string()).optional(),
  validation_checks: z.array(z.string()).optional(),
  is_active: z.boolean().optional(),
});
export type UpdateRecipeInput = z.infer<typeof UpdateRecipeInputSchema>;

// Recipe validation result
export const RecipeValidationResultSchema = z.object({
  passed: z.boolean(),
  errors: z.array(z.string()),
  warnings: z.array(z.string()),
});
export type RecipeValidationResult = z.infer<typeof RecipeValidationResultSchema>;

// Recipe list filters
export const RecipeListFiltersSchema = z.object({
  software: z.string().optional(),
  limit: z.number().int().min(1).max(100).optional(),
  offset: z.number().int().min(0).optional(),
});
export type RecipeListFilters = z.infer<typeof RecipeListFiltersSchema>;

// Recipe search input
export const RecipeSearchInputSchema = z.object({
  query: z.string().min(1, 'Search query is required'),
  limit: z.number().int().min(1).max(100).optional(),
  offset: z.number().int().min(0).optional(),
});
export type RecipeSearchInput = z.infer<typeof RecipeSearchInputSchema>;
