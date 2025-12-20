"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { api } from "@/lib/trpc/react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertCircle,
  CheckCircle,
  Play,
  Save,
  X,
  ArrowLeft,
  Loader2,
  Clock,
  FileCode,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";

// Dynamic import Monaco to avoid SSR issues
const Editor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

interface TestResult {
  success: boolean;
  error?: string;
  logs?: string;
  duration_seconds?: number;
}

export default function ReviewDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [dockerfile, setDockerfile] = useState("");
  const [aliases, setAliases] = useState<string[]>([]);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  // Fetch review item
  const { data: item, isLoading, error } = api.admin.getReviewItem.useQuery(
    { id },
    { enabled: !!id }
  );

  // Mutations
  const testBuildMutation = api.admin.testBuild.useMutation({
    onSuccess: (data) => {
      setTestResult(data);
    },
    onError: (err) => {
      setTestResult({ success: false, error: err.message });
    },
  });

  const approveMutation = api.admin.approveReview.useMutation({
    onSuccess: () => {
      router.push("/admin?tab=review&approved=true");
    },
  });

  const rejectMutation = api.admin.rejectReview.useMutation({
    onSuccess: () => {
      router.push("/admin?tab=review");
    },
  });

  // Initialize dockerfile from item
  useEffect(() => {
    if (item?.last_dockerfile) {
      setDockerfile(item.last_dockerfile);
    }
  }, [item?.last_dockerfile]);

  const handleDockerfileChange = (value: string | undefined) => {
    const newValue = value || "";
    setDockerfile(newValue);
    setHasChanges(newValue !== (item?.last_dockerfile || ""));
    // Clear test result when dockerfile changes
    if (testResult) {
      setTestResult(null);
    }
  };

  const handleTestBuild = () => {
    testBuildMutation.mutate({ dockerfile });
  };

  const handleApprove = () => {
    approveMutation.mutate({
      id,
      fixedDockerfile: dockerfile,
      aliases: aliases.filter((a) => a.trim()),
    });
  };

  const handleReject = () => {
    rejectMutation.mutate({ id, reason: "Invalid or unsupported CVE" });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !item) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <AlertCircle className="h-12 w-12 text-destructive" />
        <p className="text-lg">Failed to load review item</p>
        <Button variant="outline" onClick={() => router.back()}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Go Back
        </Button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b px-6 py-4 flex items-center justify-between bg-card">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-xl font-bold font-mono flex items-center gap-2">
              <FileCode className="h-5 w-5" />
              {item.cve_id}
            </h1>
            <p className="text-sm text-muted-foreground">
              {item.recipe_name} &bull; {item.attempts} attempts
              {item.created_at && (
                <> &bull; {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}</>
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
          <Button variant="ghost" onClick={() => router.back()}>
            <X className="h-4 w-4 mr-2" /> Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleReject}
            disabled={rejectMutation.isPending}
          >
            {rejectMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <X className="h-4 w-4 mr-2" />
            )}
            Reject
          </Button>
          <Button
            onClick={handleApprove}
            disabled={approveMutation.isPending || !testResult?.success}
            className="bg-green-600 hover:bg-green-700"
          >
            {approveMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            Approve & Push
          </Button>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Editor */}
        <div className="flex-1 flex flex-col border-r">
          <div className="bg-muted px-4 py-2 text-sm font-mono border-b flex items-center justify-between">
            <span>Dockerfile</span>
            {item.confidence_score !== null && (
              <Badge
                variant={
                  item.confidence_score >= 70
                    ? "default"
                    : item.confidence_score >= 50
                      ? "secondary"
                      : "destructive"
                }
              >
                LLM Confidence: {item.confidence_score}%
              </Badge>
            )}
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

        {/* Right: Info Panel */}
        <div className="w-96 overflow-y-auto bg-muted/30">
          {/* Confidence Reason */}
          {item.confidence_reason && (
            <Card className="m-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">LLM Analysis</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{item.confidence_reason}</p>
              </CardContent>
            </Card>
          )}

          {/* Aliases */}
          <Card className="m-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Aliases</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground mb-2">
                Common names users might search for (one per line)
              </p>
              <textarea
                value={aliases.join("\n")}
                onChange={(e) =>
                  setAliases(e.target.value.split("\n").filter(Boolean))
                }
                placeholder="log4shell&#10;log4j-rce&#10;apache-log4j"
                className="w-full h-20 bg-muted text-foreground font-mono text-sm p-2 rounded border border-input focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </CardContent>
          </Card>

          {/* Errors */}
          <Card className="m-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-destructive flex items-center gap-2">
                <AlertCircle className="h-4 w-4" />
                Build Errors ({item.errors.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {item.errors.map((err, i) => (
                <div
                  key={i}
                  className="bg-destructive/10 p-2 rounded text-destructive text-xs font-mono overflow-x-auto"
                >
                  {err}
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Test Build */}
          <Card className="m-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Test Build</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Button
                onClick={handleTestBuild}
                disabled={testBuildMutation.isPending || !dockerfile.trim()}
                className="w-full"
              >
                {testBuildMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Building...
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    Test Build
                  </>
                )}
              </Button>

              {testResult && (
                <div
                  className={`p-3 rounded ${
                    testResult.success
                      ? "bg-green-500/10 border border-green-500/30"
                      : "bg-destructive/10 border border-destructive/30"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    {testResult.success ? (
                      <>
                        <CheckCircle className="h-4 w-4 text-green-500" />
                        <span className="text-green-500 font-medium">Build Passed</span>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="h-4 w-4 text-destructive" />
                        <span className="text-destructive font-medium">Build Failed</span>
                      </>
                    )}
                    {testResult.duration_seconds && (
                      <span className="text-xs text-muted-foreground flex items-center gap-1 ml-auto">
                        <Clock className="h-3 w-3" />
                        {testResult.duration_seconds.toFixed(1)}s
                      </span>
                    )}
                  </div>
                  {testResult.error && (
                    <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap max-h-48 overflow-y-auto">
                      {testResult.error}
                    </pre>
                  )}
                  {testResult.logs && (
                    <details className="mt-2">
                      <summary className="text-xs cursor-pointer text-muted-foreground">
                        Build Logs
                      </summary>
                      <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap max-h-48 overflow-y-auto mt-2">
                        {testResult.logs}
                      </pre>
                    </details>
                  )}
                </div>
              )}

              {!testResult?.success && (
                <p className="text-xs text-muted-foreground">
                  Test build must pass before approving
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
