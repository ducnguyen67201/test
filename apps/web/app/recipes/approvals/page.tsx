'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { IntentReview } from '@/components/chat/intent-review';
import { trpc } from '@/lib/trpc/client';
import { CheckCircle2, Clock, XCircle } from 'lucide-react';
import type { Intent } from '@/lib/schemas/chat';

export default function ApprovalsPage() {
  const [selectedIntentId, setSelectedIntentId] = useState<string | null>(null);

  // Get pending intents
  const { data: pendingIntents, isLoading, refetch } = trpc.intent.getPending.useQuery({});

  const handleIntentClick = (intentId: string) => {
    setSelectedIntentId(intentId);
  };

  const handleApproved = () => {
    setSelectedIntentId(null);
    refetch();
  };

  const handleRejected = () => {
    setSelectedIntentId(null);
    refetch();
  };

  const handleBackToList = () => {
    setSelectedIntentId(null);
  };

  return (
    <div className="container mx-auto py-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Pending Intents List */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle>Pending Approvals</CardTitle>
              <CardDescription>Review and approve recipe intents</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {isLoading ? (
                <>
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-20 w-full" />
                  ))}
                </>
              ) : pendingIntents && pendingIntents.intents.length > 0 ? (
                pendingIntents.intents.map((intent) => (
                  <IntentCard
                    key={intent.id}
                    intent={intent}
                    isSelected={selectedIntentId === intent.id}
                    onClick={() => handleIntentClick(intent.id)}
                  />
                ))
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  No pending approvals
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Intent Review */}
        <div className="lg:col-span-2">
          {selectedIntentId ? (
            <>
              <Button
                variant="ghost"
                onClick={handleBackToList}
                className="mb-4 lg:hidden"
              >
                ← Back to List
              </Button>
              <IntentReview
                intentId={selectedIntentId}
                onApproved={handleApproved}
                onRejected={handleRejected}
              />
            </>
          ) : (
            <Card>
              <CardContent className="pt-12 pb-12 text-center text-muted-foreground">
                Select an intent from the list to review
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

interface IntentCardProps {
  intent: Intent;
  isSelected: boolean;
  onClick: () => void;
}

function IntentCard({ intent, isSelected, onClick }: IntentCardProps) {
  const payload = intent.payload as {
    name?: string;
    software?: string;
  };

  const getStatusIcon = () => {
    switch (intent.status) {
      case 'approved':
        return <CheckCircle2 className="h-4 w-4 text-green-500" />;
      case 'rejected':
        return <XCircle className="h-4 w-4 text-destructive" />;
      default:
        return <Clock className="h-4 w-4 text-yellow-500" />;
    }
  };

  const getStatusVariant = (): 'default' | 'secondary' | 'destructive' => {
    switch (intent.status) {
      case 'approved':
        return 'default';
      case 'rejected':
        return 'destructive';
      default:
        return 'secondary';
    }
  };

  return (
    <Card
      className={`cursor-pointer transition-all ${
        isSelected ? 'ring-2 ring-primary' : 'hover:shadow-md'
      }`}
      onClick={onClick}
    >
      <CardContent className="pt-4">
        <div className="space-y-2">
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <h4 className="font-medium text-sm line-clamp-1">
                {payload.name || 'Unnamed Recipe'}
              </h4>
              <p className="text-xs text-muted-foreground line-clamp-1">
                {payload.software || 'Unknown software'}
              </p>
            </div>
            {getStatusIcon()}
          </div>
          <div className="flex items-center justify-between">
            <Badge variant={getStatusVariant()} className="text-xs">
              {intent.status}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {Math.round(intent.confidence * 100)}%
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            {new Date(intent.created_at).toLocaleDateString()}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
