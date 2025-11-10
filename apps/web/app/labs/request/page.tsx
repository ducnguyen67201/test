'use client';

import { AuthenticatedUser } from '@/components/auth';
import { DashboardLayout } from '@/components/dashboard-layout';
import { trpc } from '@/lib/trpc/provider';
import { useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { AlertCircle } from 'lucide-react';
import { QuickPicks } from '@/components/labs/quick-picks';
import { ManualEntryForm } from '@/components/labs/manual-entry-form';
import { BlueprintCard } from '@/components/labs/blueprint-card';
import { GuardrailsPanel } from '@/components/labs/guardrails-panel';
import { RequestActions } from '@/components/labs/request-actions';
import type { LabRequest, CreateLabInput } from '@/lib/schemas/lab-request';

function RequestLabContent() {
  const [currentDraft, setCurrentDraft] = useState<LabRequest | null>(null);
  const [showManualForm, setShowManualForm] = useState(false);
  const utils = trpc.useUtils();

  // Fetch context data (quick picks, guardrails, active lab)
  const { data: context, isLoading, error } = trpc.labs.getContext.useQuery(undefined, {
    retry: 1,
  });

  // Create draft mutation
  const createDraftMutation = trpc.labs.createDraft.useMutation({
    onSuccess: (data) => {
      setCurrentDraft(data);
    },
  });

  // Generate blueprint mutation
  const generateBlueprintMutation = trpc.labs.generateBlueprint.useMutation({
    onSuccess: (data) => {
      setCurrentDraft(data);
    },
  });

  // Confirm request mutation
  const confirmRequestMutation = trpc.labs.confirmRequest.useMutation({
    onSuccess: () => {
      // Refresh context to get updated active lab
      utils.labs.getContext.invalidate();
      setCurrentDraft(null);
    },
  });

  // Loading state
  if (isLoading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="space-y-4 w-full max-w-2xl">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        </div>
      </DashboardLayout>
    );
  }

  // Error state
  if (error) {
    return (
      <DashboardLayout>
        <div className="max-w-7xl mx-auto p-6">
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              Failed to load lab context. Please try refreshing the page.
            </AlertDescription>
          </Alert>
        </div>
      </DashboardLayout>
    );
  }

  // Handle quick pick selection
  const handleQuickPickSelect = (cveId: string) => {
    const cve = context?.quick_picks.find((c) => c.id === cveId);
    if (!cve) return;

    const input: CreateLabInput = {
      source: 'quick_pick',
      cve_id: cve.id,
      title: cve.title,
      severity: cve.severity,
      description: cve.description,
      objective: '',
      ttl_hours: 4,
    };

    createDraftMutation.mutate(input, {
      onSuccess: (draft) => {
        // Auto-generate blueprint after creating draft
        generateBlueprintMutation.mutate({ labId: draft.id });
      },
    });
  };

  // Handle manual form submission
  const handleManualSubmit = (input: CreateLabInput) => {
    createDraftMutation.mutate(input, {
      onSuccess: (draft) => {
        generateBlueprintMutation.mutate({ labId: draft.id });
        setShowManualForm(false);
      },
    });
  };

  // Handle confirm request
  const handleConfirm = (justification?: string) => {
    if (!currentDraft) return;

    confirmRequestMutation.mutate({
      lab_id: currentDraft.id,
      justification,
    });
  };

  // Handle edit inputs (go back to form)
  const handleEditInputs = () => {
    setCurrentDraft(null);
    setShowManualForm(true);
  };

  // Handle refresh blueprint
  const handleRefreshBlueprint = () => {
    if (!currentDraft) return;
    generateBlueprintMutation.mutate({ labId: currentDraft.id });
  };

  const hasActiveLab = context?.active_lab != null;
  const blueprintReady = currentDraft?.blueprint != null;
  const guardrailsPassed = context?.guardrail_snapshot?.passed ?? false;

  return (
    <DashboardLayout>
      <div className="max-w-7xl mx-auto p-6">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Request Lab</h1>
          <p className="text-muted-foreground mt-2">
            Create a new CVE analysis lab with automated environment setup and guardrails
          </p>
        </div>

        {/* Active Lab Warning */}
        {hasActiveLab && (
          <Alert className="mb-6">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              You have an active lab running. Please complete or cancel it before requesting a new one.
            </AlertDescription>
          </Alert>
        )}

        {/* Two Column Layout */}
        <div className="grid grid-cols-1 min-[1024px]:grid-cols-[3fr_1.2fr] gap-6">
          {/* Left Column - Lab Creation */}
          <div className="space-y-6">
            {/* Quick Picks or Manual Form */}
            {!currentDraft && !showManualForm && (
              <QuickPicks
                quickPicks={context?.quick_picks || []}
                onSelect={handleQuickPickSelect}
                onManualEntry={() => setShowManualForm(true)}
                isLoading={createDraftMutation.isPending}
                disabled={hasActiveLab}
              />
            )}

            {!currentDraft && showManualForm && (
              <ManualEntryForm
                onSubmit={handleManualSubmit}
                onCancel={() => setShowManualForm(false)}
                isLoading={createDraftMutation.isPending}
              />
            )}

            {/* Blueprint Card */}
            {currentDraft && (
              <BlueprintCard
                labRequest={currentDraft}
                isGenerating={generateBlueprintMutation.isPending}
                onEditInputs={handleEditInputs}
                onRefresh={handleRefreshBlueprint}
              />
            )}
          </div>

          {/* Right Column - Guardrails & Actions */}
          <div className="space-y-6">
            <GuardrailsPanel
              guardrailSnapshot={context?.guardrail_snapshot}
              activeLab={context?.active_lab}
            />

            {currentDraft && (
              <RequestActions
                labRequest={currentDraft}
                blueprintReady={blueprintReady}
                guardrailsPassed={guardrailsPassed}
                onConfirm={handleConfirm}
                onEditInputs={handleEditInputs}
                isConfirming={confirmRequestMutation.isPending}
              />
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

export default function RequestLabPage() {
  return (
    <AuthenticatedUser
      accessDeniedTitle="Access Denied"
      accessDeniedMessage="Please sign in to access the Request Lab."
    >
      <RequestLabContent />
    </AuthenticatedUser>
  );
}
