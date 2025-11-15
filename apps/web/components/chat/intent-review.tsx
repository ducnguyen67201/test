'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Package,
  Server,
  Shield,
  Loader2,
  Sparkles,
} from 'lucide-react';
import { trpc } from '@/lib/trpc/client';
import type { Intent, IntentPayload } from '@/lib/schemas/chat';

interface IntentReviewProps {
  intentId: string;
  onApproved?: () => void;
  onRejected?: () => void;
}

export function IntentReview({ intentId, onApproved, onRejected }: IntentReviewProps) {
  const router = useRouter();
  const [rejectionReason, setRejectionReason] = useState('');
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [isCreatingRecipe, setIsCreatingRecipe] = useState(false);

  // Get intent details
  const { data: intent, refetch } = trpc.intent.getById.useQuery({ intentId });

  // Validate intent
  const { data: validation } = trpc.intent.validate.useMutation();

  // Create recipe from intent
  const createRecipe = trpc.recipe.createFromIntent.useMutation({
    onSuccess: (recipe) => {
      console.log('Recipe created successfully:', recipe.id);
      onApproved?.();
      // Redirect to the new recipe
      router.push(`/recipes/${recipe.id}`);
    },
    onError: (error) => {
      console.error('Failed to create recipe:', error);
      setIsCreatingRecipe(false);
    },
  });

  // Approve mutation
  const approve = trpc.intent.approve.useMutation({
    onSuccess: () => {
      console.log('Intent approved, creating recipe...');
      refetch();
      // After approval, create the recipe
      setIsCreatingRecipe(true);
      createRecipe.mutate({ intent_id: intentId });
    },
  });

  // Reject mutation
  const reject = trpc.intent.reject.useMutation({
    onSuccess: () => {
      refetch();
      onRejected?.();
    },
  });

  const handleApprove = () => {
    approve.mutate({ intentId });
  };

  const handleReject = () => {
    if (!rejectionReason.trim()) return;
    reject.mutate({ intentId, reason: rejectionReason });
  };

  if (!intent) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin" />
            Loading Intent...
          </CardTitle>
        </CardHeader>
      </Card>
    );
  }

  const payload = intent.payload as IntentPayload;
  const confidencePercent = Math.round(intent.confidence * 100);
  const isHighConfidence = intent.confidence >= 0.7;

  return (
    <div className="space-y-4">
      {/* Header Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              <CardTitle>Extracted Intent</CardTitle>
              <Badge
                variant={
                  intent.status === 'approved'
                    ? 'default'
                    : intent.status === 'rejected'
                      ? 'destructive'
                      : 'secondary'
                }
              >
                {intent.status}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Confidence:</span>
              <Badge variant={isHighConfidence ? 'default' : 'secondary'}>
                {confidencePercent}%
              </Badge>
            </div>
          </div>
          <CardDescription>
            Review the extracted environment configuration before creating a recipe
          </CardDescription>
        </CardHeader>
      </Card>

      {/* Confidence Warning */}
      {!isHighConfidence && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            Confidence score is below 70%. Please carefully review the extracted details.
          </AlertDescription>
        </Alert>
      )}

      {/* Recipe Details */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recipe Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Name & Software */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium">Recipe Name</label>
              <p className="text-sm text-muted-foreground mt-1">{payload.name}</p>
            </div>
            <div>
              <label className="text-sm font-medium flex items-center gap-1">
                <Server className="h-4 w-4" />
                Software
              </label>
              <p className="text-sm text-muted-foreground mt-1">{payload.software}</p>
            </div>
          </div>

          {/* Operating System */}
          {payload.os && (
            <div>
              <label className="text-sm font-medium">Operating System</label>
              <Badge variant="outline" className="mt-1">
                {payload.os}
              </Badge>
            </div>
          )}

          {/* Packages */}
          {payload.packages && payload.packages.length > 0 && (
            <div>
              <label className="text-sm font-medium flex items-center gap-1 mb-2">
                <Package className="h-4 w-4" />
                Packages ({payload.packages.length})
              </label>
              <div className="flex flex-wrap gap-2">
                {payload.packages.map((pkg, index) => (
                  <Badge key={index} variant="secondary">
                    {pkg.name}
                    {pkg.version && <span className="ml-1 text-xs">@{pkg.version}</span>}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* CVE Data */}
          {payload.cve_data && (
            <div>
              <label className="text-sm font-medium flex items-center gap-1 mb-2">
                <AlertTriangle className="h-4 w-4 text-destructive" />
                CVE Information
              </label>
              <div className="bg-muted rounded-md p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{payload.cve_data.id}</span>
                  {payload.cve_data.cvss_score && (
                    <Badge variant="destructive">
                      CVSS: {payload.cve_data.cvss_score.toFixed(1)}
                    </Badge>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Compliance Controls */}
          {payload.compliance_controls && payload.compliance_controls.length > 0 && (
            <div>
              <label className="text-sm font-medium flex items-center gap-1 mb-2">
                <Shield className="h-4 w-4" />
                Compliance Controls
              </label>
              <div className="flex flex-wrap gap-2">
                {payload.compliance_controls.map((control, index) => (
                  <Badge key={index} variant="outline">
                    {control.toUpperCase()}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Actions */}
      {intent.status === 'draft' && (
        <Card>
          <CardContent className="pt-6">
            {!showRejectForm ? (
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => setShowRejectForm(true)}
                  disabled={approve.isPending || reject.isPending}
                >
                  <XCircle className="h-4 w-4 mr-1" />
                  Reject
                </Button>
                <Button
                  onClick={handleApprove}
                  disabled={approve.isPending || createRecipe.isPending || reject.isPending}
                >
                  {approve.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                      Approving...
                    </>
                  ) : createRecipe.isPending || isCreatingRecipe ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                      Creating Recipe...
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="h-4 w-4 mr-1" />
                      Approve & Create Recipe
                    </>
                  )}
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="text-sm font-medium">Rejection Reason</label>
                  <Textarea
                    value={rejectionReason}
                    onChange={(e) => setRejectionReason(e.target.value)}
                    placeholder="Explain why this intent is being rejected..."
                    className="mt-1"
                    rows={3}
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowRejectForm(false);
                      setRejectionReason('');
                    }}
                    disabled={reject.isPending}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={handleReject}
                    disabled={!rejectionReason.trim() || reject.isPending}
                  >
                    {reject.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                        Rejecting...
                      </>
                    ) : (
                      <>
                        <XCircle className="h-4 w-4 mr-1" />
                        Confirm Rejection
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
