'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { FileCode2, RefreshCw, Edit, AlertTriangle, CheckCircle2, Server } from 'lucide-react';
import type { LabRequest, Blueprint } from '@/lib/schemas/lab-request';
import { getSeverityColor } from '@/lib/schemas/lab-request';

interface BlueprintCardProps {
  labRequest: LabRequest;
  isGenerating?: boolean;
  onEditInputs: () => void;
  onRefresh: () => void;
}

export function BlueprintCard({
  labRequest,
  isGenerating = false,
  onEditInputs,
  onRefresh,
}: BlueprintCardProps) {
  const blueprint = labRequest.blueprint as Blueprint | null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileCode2 className="h-5 w-5 text-primary" />
            <CardTitle>Lab Blueprint</CardTitle>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onEditInputs}
              disabled={isGenerating}
            >
              <Edit className="h-4 w-4 mr-1" />
              Edit
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={isGenerating}
            >
              <RefreshCw className={`h-4 w-4 ${isGenerating ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
        <CardDescription>
          {isGenerating
            ? 'Generating environment plan and setup instructions...'
            : 'Automated lab configuration based on your request'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Loading State */}
        {isGenerating && (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}

        {/* Blueprint Content */}
        {!isGenerating && blueprint && (
          <>
            {/* Summary */}
            <div className="space-y-2">
              <h3 className="text-sm font-semibold">Summary</h3>
              <p className="text-sm text-muted-foreground">{blueprint.summary}</p>
            </div>

            {/* Risk Badge */}
            <div className="space-y-2">
              <h3 className="text-sm font-semibold">Risk Assessment</h3>
              <div className="flex items-start gap-3 p-3 bg-muted rounded-lg">
                <AlertTriangle className="h-5 w-5 text-orange-500 mt-0.5" />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant={getSeverityColor(blueprint.risk_badge.level)}>
                      {blueprint.risk_badge.level.toUpperCase()}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {blueprint.risk_badge.reason}
                  </p>
                </div>
              </div>
            </div>

            {/* Tabbed Content */}
            <Tabs defaultValue="environment" className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="environment">Environment</TabsTrigger>
                <TabsTrigger value="validation">Validation</TabsTrigger>
                <TabsTrigger value="automation">Automation</TabsTrigger>
              </TabsList>

              {/* Environment Plan */}
              <TabsContent value="environment" className="space-y-3 mt-4">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Server className="h-4 w-4 text-muted-foreground" />
                    <h4 className="text-sm font-medium">Base Image</h4>
                  </div>
                  <p className="text-sm font-mono bg-muted px-3 py-2 rounded">
                    {blueprint.environment_plan.base_image}
                  </p>
                </div>

                <div className="space-y-2">
                  <h4 className="text-sm font-medium">Dependencies</h4>
                  <div className="flex flex-wrap gap-2">
                    {blueprint.environment_plan.dependencies.map((dep, idx) => (
                      <Badge key={idx} variant="secondary" className="font-mono text-xs">
                        {dep}
                      </Badge>
                    ))}
                  </div>
                </div>

                <div className="space-y-2">
                  <h4 className="text-sm font-medium">Configuration</h4>
                  <div className="space-y-1">
                    {Object.entries(blueprint.environment_plan.configuration).map(([key, value]) => (
                      <div
                        key={key}
                        className="flex justify-between text-sm p-2 bg-muted rounded"
                      >
                        <span className="font-medium">{key}:</span>
                        <span className="text-muted-foreground font-mono">{value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </TabsContent>

              {/* Validation Steps */}
              <TabsContent value="validation" className="space-y-2 mt-4">
                {blueprint.validation_steps.map((step, idx) => (
                  <div key={idx} className="flex items-start gap-2 p-2">
                    <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 flex-shrink-0" />
                    <span className="text-sm">{step}</span>
                  </div>
                ))}
              </TabsContent>

              {/* Automation Hooks */}
              <TabsContent value="automation" className="space-y-2 mt-4">
                {blueprint.automation_hooks.map((hook, idx) => (
                  <div key={idx} className="p-3 bg-muted rounded-lg space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{hook.name}</span>
                      <Badge variant="outline" className="text-xs">
                        {hook.stage}
                      </Badge>
                    </div>
                    <code className="text-xs font-mono text-muted-foreground block">
                      {hook.command}
                    </code>
                  </div>
                ))}
              </TabsContent>
            </Tabs>
          </>
        )}

        {/* No Blueprint Yet */}
        {!isGenerating && !blueprint && (
          <div className="text-center py-8 text-muted-foreground">
            <FileCode2 className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p>Blueprint not generated yet</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
