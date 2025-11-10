'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Shield,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
  Clock,
} from 'lucide-react';
import type { GuardrailSnapshot, LabRequest } from '@/lib/schemas/lab-request';
import { formatDistanceToNow } from 'date-fns';

interface GuardrailsPanelProps {
  guardrailSnapshot?: GuardrailSnapshot | null;
  activeLab?: LabRequest | null;
}

export function GuardrailsPanel({ guardrailSnapshot, activeLab }: GuardrailsPanelProps) {
  const getStatusIcon = (passed: boolean, severity: string) => {
    if (severity === 'error' && !passed) {
      return <XCircle className="h-4 w-4 text-destructive" />;
    }
    if (severity === 'warning') {
      return <AlertTriangle className="h-4 w-4 text-yellow-500" />;
    }
    if (passed) {
      return <CheckCircle2 className="h-4 w-4 text-green-500" />;
    }
    return <Info className="h-4 w-4 text-blue-500" />;
  };

  const getExpiryInfo = (expiresAt: string | Date | null | undefined) => {
    if (!expiresAt) return null;

    const expiry = new Date(expiresAt);
    const now = new Date();

    if (expiry <= now) {
      return { text: 'Expired', variant: 'destructive' as const };
    }

    const timeRemaining = formatDistanceToNow(expiry, { addSuffix: true });
    const hoursRemaining = (expiry.getTime() - now.getTime()) / (1000 * 60 * 60);

    if (hoursRemaining < 1) {
      return { text: `Expires ${timeRemaining}`, variant: 'destructive' as const };
    }

    return { text: `Expires ${timeRemaining}`, variant: 'secondary' as const };
  };

  const expiryInfo = activeLab ? getExpiryInfo(activeLab.expires_at) : null;

  return (
    <div className="space-y-6">
      {/* Guardrails Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            <CardTitle>Guardrails</CardTitle>
          </div>
          <CardDescription>
            Safety checks and policy enforcement
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {guardrailSnapshot ? (
            <>
              {/* Overall Status */}
              <div className="flex items-center justify-between p-3 bg-muted rounded-lg">
                <span className="text-sm font-medium">Overall Status</span>
                <Badge variant={guardrailSnapshot.passed ? 'default' : 'destructive'}>
                  {guardrailSnapshot.passed ? 'Passed' : 'Failed'}
                </Badge>
              </div>

              {/* Individual Checks */}
              <div className="space-y-2">
                {guardrailSnapshot.checks.map((check, idx) => (
                  <div
                    key={idx}
                    className="flex items-start gap-2 p-2 rounded hover:bg-muted/50 transition-colors"
                  >
                    <div className="mt-0.5">
                      {getStatusIcon(check.passed, check.severity)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-sm font-medium truncate">{check.name}</span>
                        {check.severity === 'error' && !check.passed && (
                          <Badge variant="destructive" className="text-xs flex-shrink-0">
                            Blocks
                          </Badge>
                        )}
                        {check.severity === 'warning' && (
                          <Badge variant="secondary" className="text-xs flex-shrink-0">
                            Warning
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">{check.message}</p>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="text-center py-6 text-muted-foreground">
              <Shield className="h-10 w-10 mx-auto mb-2 opacity-50" />
              <p className="text-sm">Guardrails will be evaluated when you confirm</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Active Lab Status */}
      {activeLab && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Active Lab</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription>
                <div className="space-y-2">
                  <p className="font-medium">{activeLab.title}</p>
                  <div className="flex items-center gap-2 text-sm">
                    <Badge variant={activeLab.status === 'running' ? 'default' : 'secondary'}>
                      {activeLab.status}
                    </Badge>
                    {expiryInfo && (
                      <Badge variant={expiryInfo.variant} className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {expiryInfo.text}
                      </Badge>
                    )}
                  </div>
                </div>
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>
      )}

      {/* Policy Reminders */}
      <Card className="border-blue-200 bg-blue-50/50 dark:bg-blue-950/20">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Info className="h-4 w-4 text-blue-500" />
            Policy Guidelines
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="text-sm space-y-2 text-muted-foreground">
            <li className="flex items-start gap-2">
              <span className="text-blue-500 font-bold">•</span>
              <span>Maximum 1 active lab at a time</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-500 font-bold">•</span>
              <span>Critical severity requires written justification</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-500 font-bold">•</span>
              <span>Default TTL: 4 hours (max 8 hours for admins)</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-500 font-bold">•</span>
              <span>High severity may require manager approval</span>
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
