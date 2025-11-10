import { useMemo } from 'react';
import type { LabSeverity } from '@/lib/schemas/lab-request';

export interface RequestValidationOptions {
  severity: LabSeverity;
  justification: string;
  acknowledged: boolean;
  blueprintReady: boolean;
  guardrailsPassed: boolean;
}

export interface RequestValidationResult {
  requiresJustification: boolean;
  requiresAcknowledgment: boolean;
  justificationValid: boolean;
  acknowledgmentValid: boolean;
  canConfirm: boolean;
}

export function useRequestValidation(
  options: RequestValidationOptions
): RequestValidationResult {
  const {
    severity,
    justification,
    acknowledged,
    blueprintReady,
    guardrailsPassed,
  } = options;

  return useMemo(() => {
    const requiresJustification = severity === 'critical';
    const requiresAcknowledgment = severity === 'critical' || severity === 'high';

    const justificationValid = !requiresJustification || justification.length >= 50;
    const acknowledgmentValid = !requiresAcknowledgment || acknowledged;

    const canConfirm =
      blueprintReady &&
      guardrailsPassed &&
      justificationValid &&
      acknowledgmentValid;

    return {
      requiresJustification,
      requiresAcknowledgment,
      justificationValid,
      acknowledgmentValid,
      canConfirm,
    };
  }, [severity, justification, acknowledged, blueprintReady, guardrailsPassed]);
}
