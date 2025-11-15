'use client';

import { CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Sparkles, CheckCircle2, Loader2, Coins } from 'lucide-react';
import type { ChatSession } from '@/lib/schemas/chat';

interface ChatHeaderProps {
  session?: ChatSession;
  onFinalize: () => void;
  isFinalizing: boolean;
}

export function ChatHeader({ session, onFinalize, isFinalizing }: ChatHeaderProps) {
  if (!session) {
    return (
      <CardHeader>
        <CardTitle>Chat Interface</CardTitle>
        <CardDescription>Loading session...</CardDescription>
      </CardHeader>
    );
  }

  const tokenUsagePercent = (session.token_usage / session.max_tokens) * 100;
  const isNearLimit = tokenUsagePercent > 80;

  return (
    <CardHeader>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primary" />
          <CardTitle>Recipe Chat</CardTitle>
          <Badge variant={session.status === 'open' ? 'default' : 'secondary'}>
            {session.status}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          {/* Token usage indicator */}
          <div className="flex items-center gap-1 text-sm">
            <Coins className="h-4 w-4 text-muted-foreground" />
            <span className={isNearLimit ? 'text-destructive font-medium' : 'text-muted-foreground'}>
              {session.token_usage.toLocaleString()} / {session.max_tokens.toLocaleString()}
            </span>
          </div>

          {session.status === 'open' && (
            <Button
              onClick={onFinalize}
              disabled={isFinalizing}
              size="sm"
              variant="default"
            >
              {isFinalizing ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  Extracting...
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4 mr-1" />
                  Finalize & Extract Intent
                </>
              )}
            </Button>
          )}
        </div>
      </div>
      <CardDescription>
        Describe your security testing environment. I'll help you create a recipe.
      </CardDescription>
    </CardHeader>
  );
}
