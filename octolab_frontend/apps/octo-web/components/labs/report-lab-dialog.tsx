"use client";

import { useState } from "react";
import { Flag, Loader2, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { api } from "@/lib/trpc/react";

const issueTypes = [
  {
    value: "exploit_fails",
    label: "Exploit doesn't work",
    description: "403/404/timeout when attempting exploit",
  },
  {
    value: "wont_start",
    label: "Container won't start",
    description: "Lab stuck in provisioning or errors on start",
  },
  {
    value: "connection",
    label: "Connection issues",
    description: "Can't connect via Guacamole/VNC",
  },
  {
    value: "wrong_version",
    label: "Wrong software version",
    description: "Installed version doesn't match CVE",
  },
  {
    value: "other",
    label: "Other",
    description: "Something else is wrong",
  },
] as const;

type IssueType = (typeof issueTypes)[number]["value"];

interface ReportLabDialogProps {
  labId: string;
  labName: string;
  labStatus: string;
  hasReported?: boolean;
}

export function ReportLabDialog({
  labId,
  labName,
  labStatus,
  hasReported: initialHasReported = false,
}: ReportLabDialogProps) {
  const [open, setOpen] = useState(false);
  const [issueType, setIssueType] = useState<IssueType | null>(null);
  const [attempted, setAttempted] = useState("");
  const [actual, setActual] = useState("");
  const [expected, setExpected] = useState("");
  const [includeLogs, setIncludeLogs] = useState(false);
  const [hasReported, setHasReported] = useState(initialHasReported);

  const submitMutation = api.labReport.submit.useMutation({
    onSuccess: () => {
      setHasReported(true);
      setOpen(false);
      // Reset form
      setIssueType(null);
      setAttempted("");
      setActual("");
      setExpected("");
      setIncludeLogs(false);
    },
  });

  const isValid =
    issueType && attempted.length >= 10 && actual.length >= 10;

  const handleSubmit = () => {
    if (!isValid || !issueType) return;

    submitMutation.mutate({
      labId,
      issueType,
      attempted,
      actual,
      expected: expected || undefined,
      includeLogs,
    });
  };

  // If already reported, show a different button
  if (hasReported) {
    return (
      <Button
        variant="ghost"
        size="sm"
        disabled
        className="text-muted-foreground"
      >
        <CheckCircle2 className="mr-1 h-4 w-4" />
        Reported
      </Button>
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="hover:border-destructive hover:text-destructive"
          title="Report this lab as not working"
        >
          <Flag className="mr-1 h-4 w-4" />
          Report
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Report Lab Issue</DialogTitle>
          <DialogDescription>
            <span className="font-medium">{labName}</span>
            <span className="ml-2 text-xs">Status: {labStatus}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          {/* Issue Type Selection */}
          <div className="space-y-2">
            <Label>What&apos;s the issue? *</Label>
            <div className="grid gap-2">
              {issueTypes.map((type) => (
                <label
                  key={type.value}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                    issueType === type.value
                      ? "border-primary bg-primary/5"
                      : "hover:bg-muted/50"
                  }`}
                >
                  <input
                    type="radio"
                    name="issueType"
                    value={type.value}
                    checked={issueType === type.value}
                    onChange={() => setIssueType(type.value)}
                    className="mt-1"
                  />
                  <div>
                    <div className="font-medium">{type.label}</div>
                    <div className="text-sm text-muted-foreground">
                      {type.description}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* What did you try */}
          <div className="space-y-2">
            <Label htmlFor="attempted">What did you try? *</Label>
            <Textarea
              id="attempted"
              placeholder="e.g., curl http://target/cgi-bin/.%2e/.%2e/.%2e/etc/passwd"
              value={attempted}
              onChange={(e) => setAttempted(e.target.value)}
              className="min-h-[80px]"
            />
            <p className="text-xs text-muted-foreground">
              Describe the command or exploit you attempted (min 10 chars)
            </p>
          </div>

          {/* What happened */}
          <div className="space-y-2">
            <Label htmlFor="actual">What happened? *</Label>
            <Textarea
              id="actual"
              placeholder="e.g., Got 403 Forbidden instead of file contents"
              value={actual}
              onChange={(e) => setActual(e.target.value)}
              className="min-h-[80px]"
            />
            <p className="text-xs text-muted-foreground">
              Describe the actual result (min 10 chars)
            </p>
          </div>

          {/* Expected behavior (optional) */}
          <div className="space-y-2">
            <Label htmlFor="expected">Expected behavior (optional)</Label>
            <Textarea
              id="expected"
              placeholder="e.g., Should return /etc/passwd contents"
              value={expected}
              onChange={(e) => setExpected(e.target.value)}
              className="min-h-[60px]"
            />
          </div>

          {/* Include logs checkbox */}
          <div className="flex items-center space-x-2">
            <Checkbox
              id="includeLogs"
              checked={includeLogs}
              onCheckedChange={(checked) => setIncludeLogs(checked === true)}
            />
            <Label htmlFor="includeLogs" className="text-sm font-normal">
              Include lab logs (helps debugging)
            </Label>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!isValid || submitMutation.isPending}
          >
            {submitMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Submitting...
              </>
            ) : (
              "Submit Report"
            )}
          </Button>
        </DialogFooter>

        {submitMutation.isError && (
          <p className="text-sm text-destructive">
            {submitMutation.error.message}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
