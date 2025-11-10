import { z } from 'zod';

// Lab source enum
export const LabSourceSchema = z.enum(['quick_pick', 'manual']);
export type LabSource = z.infer<typeof LabSourceSchema>;

// Lab severity enum
export const LabSeveritySchema = z.enum(['low', 'medium', 'high', 'critical']);
export type LabSeverity = z.infer<typeof LabSeveritySchema>;

// Lab status enum
export const LabStatusSchema = z.enum([
  'draft',
  'pending_guardrail',
  'rejected',
  'queued',
  'running',
  'completed',
  'expired',
]);
export type LabStatus = z.infer<typeof LabStatusSchema>;

// Create lab request input schema
export const CreateLabInputSchema = z.object({
  source: LabSourceSchema,
  cve_id: z.string().optional(),
  title: z.string().min(1, 'Title is required').max(500, 'Title is too long'),
  severity: LabSeveritySchema,
  description: z.string().optional(),
  objective: z.string().optional(),
  ttl_hours: z.number().int().min(1).max(8),
});
export type CreateLabInput = z.infer<typeof CreateLabInputSchema>;

// Confirm request input schema
export const ConfirmRequestSchema = z.object({
  lab_id: z.string().uuid(),
  justification: z.string().optional(),
  severity_acknowledged: z.boolean().optional(),
});
export type ConfirmRequest = z.infer<typeof ConfirmRequestSchema>;

// Blueprint schema
export const BlueprintSchema = z.object({
  summary: z.string(),
  risk_badge: z.object({
    level: LabSeveritySchema,
    reason: z.string(),
  }),
  environment_plan: z.object({
    base_image: z.string(),
    dependencies: z.array(z.string()),
    configuration: z.record(z.string(), z.string()),
  }),
  validation_steps: z.array(z.string()),
  automation_hooks: z.array(
    z.object({
      name: z.string(),
      command: z.string(),
      stage: z.string(),
    })
  ),
});
export type Blueprint = z.infer<typeof BlueprintSchema>;

// Guardrail check schema
export const GuardrailCheckSchema = z.object({
  name: z.string(),
  passed: z.boolean(),
  message: z.string(),
  severity: z.enum(['error', 'warning', 'info']),
});
export type GuardrailCheck = z.infer<typeof GuardrailCheckSchema>;

// Guardrail snapshot schema
export const GuardrailSnapshotSchema = z.object({
  passed: z.boolean(),
  checks: z.array(GuardrailCheckSchema),
  timestamp: z.string().or(z.date()),
});
export type GuardrailSnapshot = z.infer<typeof GuardrailSnapshotSchema>;

// Recent CVE schema
export const RecentCVESchema = z.object({
  id: z.string(),
  title: z.string(),
  severity: LabSeveritySchema,
  published_at: z.string().or(z.date()),
  exploitability_score: z.number(),
  description: z.string().optional(),
  created_at: z.string().or(z.date()),
});
export type RecentCVE = z.infer<typeof RecentCVESchema>;

// Lab request schema
export const LabRequestSchema = z.object({
  id: z.string().uuid(),
  user_id: z.string().uuid(),
  source: LabSourceSchema,
  cve_id: z.string().optional(),
  title: z.string(),
  severity: LabSeveritySchema,
  description: z.string().optional(),
  objective: z.string().optional(),
  ttl_hours: z.number(),
  expires_at: z.string().or(z.date()).nullable(),
  status: LabStatusSchema,
  blueprint: BlueprintSchema.nullable().optional(),
  guardrail_snapshot: GuardrailSnapshotSchema.nullable().optional(),
  risk_rating: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: z.string().or(z.date()),
  updated_at: z.string().or(z.date()),
});
export type LabRequest = z.infer<typeof LabRequestSchema>;

// Lab context schema (response from GET /labs/context)
export const LabContextSchema = z.object({
  quick_picks: z.array(RecentCVESchema),
  guardrail_snapshot: GuardrailSnapshotSchema,
  active_lab: LabRequestSchema.nullable().optional(),
});
export type LabContext = z.infer<typeof LabContextSchema>;

// Badge variant type
export type BadgeVariant = 'default' | 'secondary' | 'destructive' | 'outline';

// Helper functions for severity badge styling
export function getSeverityColor(severity: LabSeverity): BadgeVariant {
  switch (severity) {
    case 'critical':
      return 'destructive';
    case 'high':
      return 'destructive';
    case 'medium':
      return 'default';
    case 'low':
      return 'secondary';
  }
}

export function getSeverityTextColor(severity: LabSeverity): string {
  switch (severity) {
    case 'critical':
      return 'text-red-600 dark:text-red-400';
    case 'high':
      return 'text-orange-600 dark:text-orange-400';
    case 'medium':
      return 'text-yellow-600 dark:text-yellow-400';
    case 'low':
      return 'text-blue-600 dark:text-blue-400';
  }
}
