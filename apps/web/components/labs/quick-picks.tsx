'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { FlaskConical, Clock, AlertTriangle } from 'lucide-react';
import type { RecentCVE } from '@/lib/schemas/lab-request';
import { getSeverityColor } from '@/lib/schemas/lab-request';
import { formatDistanceToNow } from 'date-fns';

interface QuickPicksProps {
  quickPicks: RecentCVE[];
  onSelect: (cveId: string) => void;
  onManualEntry: () => void;
  isLoading?: boolean;
  disabled?: boolean;
}

export function QuickPicks({
  quickPicks,
  onSelect,
  onManualEntry,
  isLoading = false,
  disabled = false,
}: QuickPicksProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5 text-primary" />
            <CardTitle>New Lab</CardTitle>
          </div>
        </div>
        <CardDescription>
          Select a recent CVE or create a custom lab request
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Quick Picks */}
        <div>
          <h3 className="text-sm font-medium mb-3">Quick Picks</h3>
          {quickPicks.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <FlaskConical className="h-12 w-12 mx-auto mb-3 opacity-50" />
              <p>No recent CVEs available</p>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {quickPicks.map((cve) => {
                const publishedDate = new Date(cve.published_at);
                const timeAgo = formatDistanceToNow(publishedDate, { addSuffix: true });

                return (
                  <Button
                    key={cve.id}
                    variant="outline"
                    className="h-auto flex-col items-start p-3 hover:border-primary"
                    onClick={() => onSelect(cve.id)}
                    disabled={disabled || isLoading}
                  >
                    <div className="flex items-center gap-2 mb-1 w-full">
                      <Badge variant={getSeverityColor(cve.severity)} className="text-xs">
                        {cve.severity.toUpperCase()}
                      </Badge>
                      <span className="font-mono text-xs font-semibold">{cve.id}</span>
                    </div>
                    <div className="text-left text-sm line-clamp-2 mb-1">
                      {cve.title}
                    </div>
                    <div className="flex items-center gap-4 text-xs text-muted-foreground w-full">
                      <div className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        <span>{timeAgo}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        <span>{cve.exploitability_score.toFixed(1)}</span>
                      </div>
                    </div>
                  </Button>
                );
              })}
            </div>
          )}
        </div>

        {/* Manual Entry Option */}
        <div className="border-t pt-4">
          <Button
            variant="secondary"
            className="w-full"
            onClick={onManualEntry}
            disabled={disabled || isLoading}
          >
            Manual Entry
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
