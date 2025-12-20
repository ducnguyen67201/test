"use client";

import { useState } from "react";
import {
  Play,
  Square,
  Clock,
  ExternalLink,
  RotateCw,
  Trash2,
  Loader2,
  Server,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/trpc/react";
import { cn } from "@/lib/utils";
import { ReportLabDialog } from "@/components/labs/report-lab-dialog";

type LabStatus = "requested" | "provisioning" | "ready" | "degraded" | "connecting" | "connected" | "stopped" | "error" | "expired";

const statusConfig: Record<LabStatus, { bg: string; text: string; dot: string; label: string }> = {
  requested: { bg: "bg-blue-50 dark:bg-blue-950", text: "text-blue-700 dark:text-blue-300", dot: "bg-blue-500", label: "Requested" },
  provisioning: { bg: "bg-yellow-50 dark:bg-yellow-950", text: "text-yellow-700 dark:text-yellow-300", dot: "bg-yellow-500", label: "Deploying" },
  ready: { bg: "bg-green-50 dark:bg-green-950", text: "text-green-700 dark:text-green-300", dot: "bg-green-500", label: "Ready" },
  degraded: { bg: "bg-orange-50 dark:bg-orange-950", text: "text-orange-700 dark:text-orange-300", dot: "bg-orange-500", label: "Degraded" },
  connecting: { bg: "bg-blue-50 dark:bg-blue-950", text: "text-blue-700 dark:text-blue-300", dot: "bg-blue-500", label: "Connecting" },
  connected: { bg: "bg-green-50 dark:bg-green-950", text: "text-green-700 dark:text-green-300", dot: "bg-green-500", label: "Connected" },
  stopped: { bg: "bg-gray-50 dark:bg-gray-900", text: "text-gray-600 dark:text-gray-400", dot: "bg-gray-400", label: "Stopped" },
  expired: { bg: "bg-red-50 dark:bg-red-950", text: "text-red-700 dark:text-red-300", dot: "bg-red-500", label: "Expired" },
  error: { bg: "bg-red-50 dark:bg-red-950", text: "text-red-700 dark:text-red-300", dot: "bg-red-500", label: "Error" },
};

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTimeAgo(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(dateString);
}

function LabStatusBadge({ status }: { status: LabStatus }) {
  const config = statusConfig[status] ?? statusConfig.error;
  const isProvisioning = status === "provisioning";

  return (
    <Badge variant="outline" className={cn("gap-1.5", config.bg, config.text)}>
      <div className={cn("h-1.5 w-1.5 rounded-full", config.dot, isProvisioning && "animate-pulse")} />
      {config.label}
    </Badge>
  );
}

interface Lab {
  id: string;
  status: LabStatus;
  connectionUrl: string | null;
  expiresAt: string | null;
  createdAt: string;
  updatedAt: string;
  recipe: {
    id: string;
    name: string;
    software: string;
    exploitFamily: string | null;
  };
}

function LabsTable({ labs, isLoading }: { labs: Lab[]; isLoading: boolean }) {
  const utils = api.useUtils();

  const stopMutation = api.lab.stop.useMutation({
    onSuccess: () => {
      utils.lab.list.invalidate();
      utils.lab.listActive.invalidate();
      utils.lab.stats.invalidate();
    },
  });

  const restartMutation = api.lab.restart.useMutation({
    onSuccess: () => {
      utils.lab.list.invalidate();
      utils.lab.listActive.invalidate();
      utils.lab.stats.invalidate();
    },
  });

  const deleteMutation = api.lab.delete.useMutation({
    onSuccess: () => {
      utils.lab.list.invalidate();
      utils.lab.listActive.invalidate();
      utils.lab.stats.invalidate();
    },
  });

  const handleConnect = (lab: Lab) => {
    // Use our API proxy route which handles authentication with the backend
    window.open(`/api/labs/${lab.id}/connect`, "_blank");
  };

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-4 p-4 border rounded-lg">
            <Skeleton className="h-10 w-10 rounded-md" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-1/4" />
            </div>
            <Skeleton className="h-8 w-20" />
          </div>
        ))}
      </div>
    );
  }

  if (labs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Server className="h-12 w-12 text-muted-foreground/50" />
        <h3 className="mt-4 text-lg font-semibold">No labs found</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Start a new lab from the Chat page to see it here.
        </p>
        <Button className="mt-4" asChild>
          <a href="/chat">Go to Chat</a>
        </Button>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Lab</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Created</TableHead>
          <TableHead>Expires</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {labs.map((lab) => {
          const isActive = ["provisioning", "ready", "degraded", "connecting", "connected"].includes(lab.status);
          const isReady = lab.status === "ready" || lab.status === "degraded" || lab.status === "connected";
          const isDegraded = lab.status === "degraded";
          const isStopped = lab.status === "stopped";
          const canDelete = ["stopped", "expired", "error"].includes(lab.status);
          const canReport = ["ready", "degraded", "connected", "error"].includes(lab.status);

          return (
            <TableRow key={lab.id}>
              <TableCell>
                <div>
                  <p className="font-medium">{lab.recipe.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {lab.recipe.software}
                    {lab.recipe.exploitFamily && ` • ${lab.recipe.exploitFamily}`}
                  </p>
                  <code className="text-[10px] text-muted-foreground">{lab.id.slice(0, 12)}...</code>
                </div>
              </TableCell>
              <TableCell>
                <div className="flex flex-col gap-1">
                  <LabStatusBadge status={lab.status} />
                  {isDegraded && (
                    <span className="text-[10px] text-orange-600 dark:text-orange-400 flex items-center gap-1">
                      <AlertCircle className="h-3 w-3" />
                      Target crashed
                    </span>
                  )}
                </div>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {formatTimeAgo(lab.createdAt)}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {lab.expiresAt ? formatDate(lab.expiresAt) : "-"}
              </TableCell>
              <TableCell className="text-right">
                <div className="flex items-center justify-end gap-1">
                  {isReady && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7"
                      onClick={() => handleConnect(lab)}
                    >
                      <ExternalLink className="mr-1 h-3 w-3" />
                      Connect
                    </Button>
                  )}

                  {canReport && (
                    <ReportLabDialog
                      labId={lab.id}
                      labName={lab.recipe.name}
                      labStatus={lab.status}
                    />
                  )}

                  {isActive && lab.status !== "provisioning" && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7"
                      onClick={() => stopMutation.mutate({ labId: lab.id })}
                      disabled={stopMutation.isPending}
                    >
                      {stopMutation.isPending ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Square className="h-3 w-3" />
                      )}
                    </Button>
                  )}

                  {isStopped && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7"
                      onClick={() => restartMutation.mutate({ labId: lab.id })}
                      disabled={restartMutation.isPending}
                    >
                      {restartMutation.isPending ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <RotateCw className="h-3 w-3" />
                      )}
                    </Button>
                  )}

                  {canDelete && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-destructive hover:text-destructive"
                      onClick={() => deleteMutation.mutate({ labId: lab.id })}
                      disabled={deleteMutation.isPending}
                    >
                      {deleteMutation.isPending ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Trash2 className="h-3 w-3" />
                      )}
                    </Button>
                  )}
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export default function LabsPage() {
  const [activeTab, setActiveTab] = useState("active");

  const { data: stats, isLoading: statsLoading } = api.lab.stats.useQuery();
  const { data: activeLabs, isLoading: activeLoading } = api.lab.listActive.useQuery();
  const { data: allLabs, isLoading: allLoading } = api.lab.list.useQuery({ limit: 50 });

  const historyLabs = allLabs?.labs.filter(
    (lab) => ["stopped", "expired", "error"].includes(lab.status)
  ) ?? [];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Labs</h2>
        <p className="text-muted-foreground">
          View and manage all your lab environments.
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Labs</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold">{stats?.total ?? 0}</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active</CardTitle>
            <Play className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold text-green-600">{stats?.active ?? 0}</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Ready</CardTitle>
            <Clock className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold text-blue-600">{stats?.ready ?? 0}</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Stopped</CardTitle>
            <AlertCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold text-muted-foreground">{stats?.stopped ?? 0}</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Labs Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="active" className="gap-2">
            <Play className="h-3.5 w-3.5" />
            Active
            {(stats?.active ?? 0) > 0 && (
              <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                {stats?.active}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="all" className="gap-2">
            <Server className="h-3.5 w-3.5" />
            All Labs
          </TabsTrigger>
          <TabsTrigger value="history" className="gap-2">
            <Clock className="h-3.5 w-3.5" />
            History
            {historyLabs.length > 0 && (
              <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                {historyLabs.length}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="active" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Active Labs</CardTitle>
              <CardDescription>
                Labs that are currently running or being provisioned.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <LabsTable labs={activeLabs ?? []} isLoading={activeLoading} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="all" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>All Labs</CardTitle>
              <CardDescription>
                Complete list of all your labs.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <LabsTable labs={allLabs?.labs ?? []} isLoading={allLoading} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="history" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Lab History</CardTitle>
              <CardDescription>
                Past labs that have been stopped, expired, or encountered errors.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <LabsTable labs={historyLabs} isLoading={allLoading} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
