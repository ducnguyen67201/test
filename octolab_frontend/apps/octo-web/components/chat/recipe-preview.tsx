"use client";

import { Server, GitBranch, Shield, Play, Loader2, FileCode, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface Recipe {
  name: string;
  description?: string | null;
  software: string;
  version_constraint?: string | null;
  exploit_family?: string | null;
  is_active?: boolean;
}

interface RecipePreviewProps {
  recipe: Recipe;
  onDeploy?: () => void;
  isDeploying?: boolean;
  onGenerateDockerfile?: () => void;
  isGenerating?: boolean;
  hasDockerfile?: boolean;
  className?: string;
}

const exploitFamilyColors: Record<string, string> = {
  path_traversal: "bg-yellow-100 text-yellow-800 border-yellow-200",
  rce: "bg-red-100 text-red-800 border-red-200",
  sql_injection: "bg-purple-100 text-purple-800 border-purple-200",
  xss: "bg-orange-100 text-orange-800 border-orange-200",
  ssrf: "bg-blue-100 text-blue-800 border-blue-200",
  deserialization: "bg-pink-100 text-pink-800 border-pink-200",
  buffer_overflow: "bg-gray-100 text-gray-800 border-gray-200",
  privilege_escalation: "bg-indigo-100 text-indigo-800 border-indigo-200",
  authentication_bypass: "bg-cyan-100 text-cyan-800 border-cyan-200",
  information_disclosure: "bg-teal-100 text-teal-800 border-teal-200",
};

export function RecipePreview({
  recipe,
  onDeploy,
  isDeploying,
  onGenerateDockerfile,
  isGenerating,
  hasDockerfile,
  className,
}: RecipePreviewProps) {
  const exploitColor =
    recipe.exploit_family && exploitFamilyColors[recipe.exploit_family]
      ? exploitFamilyColors[recipe.exploit_family]
      : "bg-gray-100 text-gray-800 border-gray-200";

  return (
    <div
      className={cn(
        "rounded-lg border bg-gradient-to-br from-slate-50 to-slate-100 p-4",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-100">
            <Shield className="h-5 w-5 text-orange-600" />
          </div>
          <div>
            <h4 className="font-semibold text-sm">{recipe.name}</h4>
            {recipe.exploit_family && (
              <Badge
                variant="outline"
                className={cn("mt-1 text-xs capitalize", exploitColor)}
              >
                {recipe.exploit_family.replace(/_/g, " ")}
              </Badge>
            )}
          </div>
        </div>
      </div>

      {/* Description */}
      {recipe.description && (
        <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
          {recipe.description}
        </p>
      )}

      {/* Details Grid */}
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="flex items-center gap-2 text-sm">
          <Server className="h-4 w-4 text-muted-foreground" />
          <span className="text-muted-foreground">Software:</span>
          <span className="font-medium">{recipe.software}</span>
        </div>
        {recipe.version_constraint && (
          <div className="flex items-center gap-2 text-sm">
            <GitBranch className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">Version:</span>
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">
              {recipe.version_constraint}
            </code>
          </div>
        )}
      </div>

      {/* Action Buttons */}
      {(onGenerateDockerfile || onDeploy) && (
        <div className="mt-4 pt-4 border-t space-y-2">
          {/* Step 1: Generate Dockerfile (if not yet generated) */}
          {onGenerateDockerfile && !hasDockerfile && (
            <Button
              onClick={onGenerateDockerfile}
              disabled={isGenerating}
              variant="outline"
              className="w-full"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Generating Dockerfile...
                </>
              ) : (
                <>
                  <FileCode className="mr-2 h-4 w-4" />
                  Generate Dockerfile
                </>
              )}
            </Button>
          )}

          {/* Dockerfile ready indicator */}
          {hasDockerfile && (
            <div className="flex items-center gap-2 text-sm text-green-600">
              <Check className="h-4 w-4" />
              <span>Dockerfile ready</span>
            </div>
          )}

          {/* Step 2: Deploy (always available, but works best after dockerfile is ready) */}
          {onDeploy && (
            <Button
              onClick={onDeploy}
              disabled={isDeploying || isGenerating}
              className="w-full bg-orange-500 hover:bg-orange-600"
            >
              {isDeploying ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Deploying Lab...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Deploy Lab Environment
                </>
              )}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
