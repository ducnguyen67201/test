'use client';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useState } from 'react';
import type { LabRequest } from '@/lib/schemas/lab-request';
import { useRequestValidation } from '@/hooks/use-request-validation';

interface RequestActionsProps {
  labRequest: LabRequest;
  blueprintReady: boolean;
  guardrailsPassed: boolean;
  onConfirm: (justification?: string) => void;
  onEditInputs: () => void;
  isConfirming?: boolean;
}

export function RequestActions({
  labRequest,
  blueprintReady,
  guardrailsPassed,
  onConfirm,
  onEditInputs,
  isConfirming = false,
}: RequestActionsProps) {
  const [justification, setJustification] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);

  const validation = useRequestValidation({
    severity: labRequest.severity,
    justification,
    acknowledged,
    blueprintReady,
    guardrailsPassed,
  });

  const {
    requiresJustification,
    requiresAcknowledgment,
    justificationValid,
    acknowledgmentValid,
    canConfirm: canConfirmBase,
  } = validation;

  const canConfirm = canConfirmBase && !isConfirming;

  const handleConfirm = () => {
    if (!canConfirm) return;
    onConfirm(justification || undefined);
  };

  return (
    <Card>
      <CardContent className="pt-6 space-y-4">
        {/* Critical Severity - Justification Required */}
        {requiresJustification && (
          <div className="space-y-2">
            <Label htmlFor="justification">
              Justification <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="justification"
              placeholder="Provide detailed justification for this critical severity lab (minimum 50 characters)"
              rows={4}
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              disabled={isConfirming}
            />
            <p className="text-xs text-muted-foreground">
              {justification.length} / 50 characters
            </p>
          </div>
        )}

        {/* High/Critical Severity - Acknowledgment */}
        {requiresAcknowledgment && (
          <Alert>
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              <div className="space-y-2">
                <p className="font-medium">
                  {labRequest.severity === 'critical' ? 'Critical' : 'High'} Severity Lab
                </p>
                <p className="text-sm">
                  This lab involves{' '}
                  {labRequest.severity === 'critical' ? 'critical' : 'high'} severity
                  vulnerabilities and requires strict isolation and monitoring.
                </p>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={acknowledged}
                    onChange={(e) => setAcknowledged(e.target.checked)}
                    disabled={isConfirming}
                    className="mt-1"
                  />
                  <span className="text-sm">
                    I understand the risks and will follow all security protocols
                  </span>
                </label>
              </div>
            </AlertDescription>
          </Alert>
        )}

        {/* Readiness Checks */}
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2">
            {blueprintReady ? (
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
            )}
            <span className={blueprintReady ? 'text-green-700 dark:text-green-400' : ''}>
              Blueprint generated
            </span>
          </div>
          <div className="flex items-center gap-2">
            {guardrailsPassed ? (
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
            )}
            <span className={guardrailsPassed ? 'text-green-700 dark:text-green-400' : ''}>
              Guardrails passed
            </span>
          </div>
          {requiresJustification && (
            <div className="flex items-center gap-2">
              {justificationValid ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <AlertTriangle className="h-4 w-4 text-yellow-500" />
              )}
              <span className={justificationValid ? 'text-green-700 dark:text-green-400' : ''}>
                Justification provided
              </span>
            </div>
          )}
          {requiresAcknowledgment && (
            <div className="flex items-center gap-2">
              {acknowledgmentValid ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <AlertTriangle className="h-4 w-4 text-yellow-500" />
              )}
              <span className={acknowledgmentValid ? 'text-green-700 dark:text-green-400' : ''}>
                Risks acknowledged
              </span>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2 pt-2">
          <Button
            variant="outline"
            onClick={onEditInputs}
            disabled={isConfirming}
            className="flex-1"
          >
            Edit Inputs
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={!canConfirm}
            className="flex-1"
          >
            {isConfirming ? 'Confirming...' : 'Confirm Request'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
