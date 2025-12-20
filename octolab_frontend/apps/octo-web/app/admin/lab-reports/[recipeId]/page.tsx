"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { api } from "@/lib/trpc/react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertCircle,
  CheckCircle,
  ArrowLeft,
  Loader2,
  Flag,
  FileCode,
  User,
  Clock,
  Save,
  CheckCircle2,
  XCircle,
  Search,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";

// Dynamic import Monaco to avoid SSR issues
const Editor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

type ReportStatus = "open" | "investigating" | "fixed" | "wont_fix" | "duplicate";

const statusConfig: Record<ReportStatus, { label: string; variant: "default" | "secondary" | "destructive" | "outline"; icon: React.ReactNode }> = {
  open: { label: "Open", variant: "destructive", icon: <AlertCircle className="h-3 w-3" /> },
  investigating: { label: "Investigating", variant: "secondary", icon: <Search className="h-3 w-3" /> },
  fixed: { label: "Fixed", variant: "default", icon: <CheckCircle2 className="h-3 w-3" /> },
  wont_fix: { label: "Won't Fix", variant: "outline", icon: <XCircle className="h-3 w-3" /> },
  duplicate: { label: "Duplicate", variant: "outline", icon: <XCircle className="h-3 w-3" /> },
};

const issueTypeLabels: Record<string, string> = {
  exploit_fails: "Exploit doesn't work",
  wont_start: "Container won't start",
  connection: "Connection issues",
  wrong_version: "Wrong software version",
  other: "Other",
};

export default function LabReportsDetailPage() {
  const params = useParams();
  const router = useRouter();
  const recipeId = params.recipeId as string;

  const [dockerfile, setDockerfile] = useState("");
  const [hasChanges, setHasChanges] = useState(false);
  const [selectedReport, setSelectedReport] = useState<string | null>(null);

  // Fetch reports for this recipe
  const { data, isLoading, error, refetch } = api.labReport.getByRecipe.useQuery(
    { recipeId },
    { enabled: !!recipeId }
  );

  // Mutations
  const updateStatusMutation = api.labReport.updateStatus.useMutation({
    onSuccess: () => {
      refetch();
    },
  });

  const bulkResolveMutation = api.labReport.bulkResolve.useMutation({
    onSuccess: () => {
      refetch();
    },
  });

  const updateDockerfileMutation = api.recipe.updateDockerfile.useMutation({
    onSuccess: () => {
      setHasChanges(false);
      refetch();
    },
  });

  // Initialize dockerfile from recipe
  useEffect(() => {
    if (data?.recipe?.dockerfile) {
      setDockerfile(data.recipe.dockerfile);
    }
  }, [data?.recipe?.dockerfile]);

  const handleDockerfileChange = (value: string | undefined) => {
    const newValue = value || "";
    setDockerfile(newValue);
    setHasChanges(newValue !== (data?.recipe?.dockerfile || ""));
  };

  const handleSaveDockerfile = () => {
    updateDockerfileMutation.mutate({
      id: recipeId,
      dockerfile,
    });
  };

  const handleBulkResolve = (status: "fixed" | "wont_fix" | "duplicate") => {
    bulkResolveMutation.mutate({
      recipeId,
      status,
      adminNotes: status === "fixed" ? "Fixed by updating Dockerfile" : undefined,
    });
  };

  const handleStatusChange = (reportId: string, status: ReportStatus) => {
    updateStatusMutation.mutate({ id: reportId, status });
  };

  const openReports = data?.reports?.filter(
    (r) => r.status === "open" || r.status === "investigating"
  ) ?? [];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <AlertCircle className="h-12 w-12 text-destructive" />
        <p className="text-lg">Failed to load recipe reports</p>
        <Button variant="outline" onClick={() => router.back()}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Go Back
        </Button>
      </div>
    );
  }

  const { recipe, reports } = data;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b px-6 py-4 flex items-center justify-between bg-card">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push("/admin?tab=reports")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-xl font-bold flex items-center gap-2">
              <Flag className="h-5 w-5" />
              {recipe.name}
            </h1>
            <p className="text-sm text-muted-foreground">
              {recipe.software} &bull; {reports.length} report{reports.length !== 1 ? "s" : ""}
              {openReports.length > 0 && (
                <> &bull; <span className="text-destructive">{openReports.length} open</span></>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {hasChanges && (
            <Badge variant="outline" className="text-yellow-500 border-yellow-500">
              Unsaved Changes
            </Badge>
          )}
          {openReports.length > 0 && (
            <>
              <Button
                variant="outline"
                onClick={() => handleBulkResolve("wont_fix")}
                disabled={bulkResolveMutation.isPending}
              >
                <XCircle className="h-4 w-4 mr-2" />
                Won&apos;t Fix All
              </Button>
              <Button
                onClick={() => handleBulkResolve("fixed")}
                disabled={bulkResolveMutation.isPending}
                className="bg-green-600 hover:bg-green-700"
              >
                {bulkResolveMutation.isPending ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <CheckCircle className="h-4 w-4 mr-2" />
                )}
                Resolve All as Fixed
              </Button>
            </>
          )}
          <Button
            onClick={handleSaveDockerfile}
            disabled={!hasChanges || updateDockerfileMutation.isPending}
          >
            {updateDockerfileMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            Save Dockerfile
          </Button>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Editor */}
        <div className="flex-1 flex flex-col border-r">
          <div className="bg-muted px-4 py-2 text-sm font-mono border-b flex items-center justify-between">
            <span className="flex items-center gap-2">
              <FileCode className="h-4 w-4" />
              Dockerfile
            </span>
          </div>
          <div className="flex-1">
            <Editor
              height="100%"
              defaultLanguage="dockerfile"
              theme="vs-dark"
              value={dockerfile}
              onChange={handleDockerfileChange}
              options={{
                minimap: { enabled: false },
                fontSize: 14,
                lineNumbers: "on",
                scrollBeyondLastLine: false,
                automaticLayout: true,
                wordWrap: "on",
                padding: { top: 16 },
              }}
            />
          </div>
        </div>

        {/* Right: Reports Panel */}
        <div className="w-[500px] overflow-y-auto bg-muted/30">
          <div className="p-4 border-b">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Flag className="h-5 w-5" />
              User Reports ({reports.length})
            </h2>
            <p className="text-sm text-muted-foreground">
              Issues reported by users for this recipe
            </p>
          </div>

          {reports.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <Flag className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No reports for this recipe</p>
            </div>
          ) : (
            <div className="space-y-4 p-4">
              {reports.map((report) => {
                const statusInfo = statusConfig[report.status as ReportStatus] || statusConfig.open;
                const isExpanded = selectedReport === report.id;

                return (
                  <Card
                    key={report.id}
                    className={`cursor-pointer transition-colors ${
                      isExpanded ? "ring-2 ring-primary" : "hover:bg-muted/50"
                    }`}
                    onClick={() => setSelectedReport(isExpanded ? null : report.id)}
                  >
                    <CardHeader className="pb-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Badge variant={statusInfo.variant} className="gap-1">
                            {statusInfo.icon}
                            {statusInfo.label}
                          </Badge>
                          <Badge variant="outline">
                            {issueTypeLabels[report.issueType] || report.issueType}
                          </Badge>
                        </div>
                        <div
                          className="flex items-center gap-1"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Select
                            value={report.status}
                            onValueChange={(value) =>
                              handleStatusChange(report.id, value as ReportStatus)
                            }
                          >
                            <SelectTrigger className="h-7 w-28 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="open">Open</SelectItem>
                              <SelectItem value="investigating">Investigating</SelectItem>
                              <SelectItem value="fixed">Fixed</SelectItem>
                              <SelectItem value="wont_fix">Won&apos;t Fix</SelectItem>
                              <SelectItem value="duplicate">Duplicate</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-muted-foreground mt-1">
                        <span className="flex items-center gap-1">
                          <User className="h-3 w-3" />
                          {report.user.name || report.user.email}
                        </span>
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatDistanceToNow(new Date(report.createdAt), { addSuffix: true })}
                        </span>
                      </div>
                    </CardHeader>

                    {isExpanded && (
                      <CardContent className="space-y-3 pt-2">
                        <div>
                          <p className="text-xs font-medium text-muted-foreground mb-1">
                            What they tried:
                          </p>
                          <div className="bg-muted p-2 rounded text-sm font-mono whitespace-pre-wrap">
                            {report.attempted}
                          </div>
                        </div>

                        <div>
                          <p className="text-xs font-medium text-muted-foreground mb-1">
                            What happened:
                          </p>
                          <div className="bg-destructive/10 p-2 rounded text-sm whitespace-pre-wrap text-destructive">
                            {report.actual}
                          </div>
                        </div>

                        {report.expected && (
                          <div>
                            <p className="text-xs font-medium text-muted-foreground mb-1">
                              Expected behavior:
                            </p>
                            <div className="bg-green-500/10 p-2 rounded text-sm whitespace-pre-wrap text-green-600">
                              {report.expected}
                            </div>
                          </div>
                        )}

                        {report.includeLogs && (
                          <Badge variant="outline" className="text-xs">
                            User requested to include logs
                          </Badge>
                        )}

                        <div className="text-xs text-muted-foreground">
                          Lab ID: <code className="bg-muted px-1 rounded">{report.lab.id.slice(0, 12)}...</code>
                          {" "}
                          Status: {report.lab.status}
                        </div>
                      </CardContent>
                    )}
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
