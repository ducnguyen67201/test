"use client";

import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";

export interface ActiveLab {
  id: string;
  status: string;
  createdAt: string;
  recipe: {
    id: string;
    name: string;
    software: string;
    exploitFamily: string | null;
  };
}

interface QuotaExceededModalProps {
  isOpen: boolean;
  activeLabs: ActiveLab[];
  onTerminateAndRetry: (labIds: string[]) => Promise<void>;
  onCancel: () => void;
  isTerminating: boolean;
  terminationProgress: number;
  terminationStatus: string;
}

export function QuotaExceededModal({
  isOpen,
  activeLabs,
  onTerminateAndRetry,
  onCancel,
  isTerminating,
  terminationProgress,
  terminationStatus,
}: QuotaExceededModalProps) {
  // Debug: log what the modal receives
  console.log("[QuotaModal] isOpen:", isOpen, "activeLabs:", activeLabs);

  const labsArray = Array.isArray(activeLabs) ? activeLabs : [];
  console.log("[QuotaModal] labsArray length:", labsArray.length, "first lab:", labsArray[0]);

  // Only selectable labs are those NOT already ending
  const selectableLabs = labsArray.filter((lab) => lab.status !== "ending");
  const endingLabs = labsArray.filter((lab) => lab.status === "ending");
  console.log("[QuotaModal] selectableLabs:", selectableLabs.length, "endingLabs:", endingLabs.length);

  const [selectedLabIds, setSelectedLabIds] = useState<Set<string>>(
    new Set(selectableLabs.map((lab) => lab.id))
  );

  const allSelected = selectedLabIds.size === selectableLabs.length && selectableLabs.length > 0;
  const noneSelected = selectedLabIds.size === 0;

  // Update selections when activeLabs changes (only select non-ending labs)
  useEffect(() => {
    const newSelectableLabs = labsArray.filter((lab) => lab.status !== "ending");
    if (newSelectableLabs.length > 0) {
      setSelectedLabIds(new Set(newSelectableLabs.map((lab) => lab.id)));
    } else {
      setSelectedLabIds(new Set());
    }
  }, [activeLabs]);

  const toggleLab = (labId: string) => {
    const newSet = new Set(selectedLabIds);
    if (newSet.has(labId)) {
      newSet.delete(labId);
    } else {
      newSet.add(labId);
    }
    setSelectedLabIds(newSet);
  };

  const toggleAll = () => {
    if (allSelected) {
      setSelectedLabIds(new Set());
    } else {
      // Only select non-ending labs
      setSelectedLabIds(new Set(selectableLabs.map((lab) => lab.id)));
    }
  };

  const handleTerminate = async () => {
    if (selectedLabIds.size === 0) return;
    await onTerminateAndRetry(Array.from(selectedLabIds));
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !isTerminating && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Lab Quota Exceeded</DialogTitle>
          <DialogDescription>
            You&apos;ve reached the maximum number of active labs. Select labs to
            terminate before creating a new one.
            {endingLabs.length > 0 && (
              <span className="block mt-1 text-yellow-600 dark:text-yellow-400">
                {endingLabs.length} lab{endingLabs.length > 1 ? "s" : ""} already stopping...
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {isTerminating ? (
          <div className="py-6 space-y-4">
            <div className="text-sm text-muted-foreground text-center">
              {terminationStatus}
            </div>
            <Progress value={terminationProgress} className="h-2" />
            <div className="text-xs text-muted-foreground text-center">
              {Math.round(terminationProgress)}% complete
            </div>
          </div>
        ) : (
          <div className="py-4 space-y-3">
            {/* Select All - only show if there are selectable labs */}
            {selectableLabs.length > 0 && (
              <div className="flex items-center space-x-3 pb-2 border-b">
                <Checkbox
                  id="select-all"
                  checked={allSelected}
                  onCheckedChange={toggleAll}
                />
                <label
                  htmlFor="select-all"
                  className="text-sm font-medium cursor-pointer"
                >
                  Select All ({selectableLabs.length} lab{selectableLabs.length !== 1 ? "s" : ""})
                </label>
              </div>
            )}

            {/* Lab List */}
            <div className="max-h-64 overflow-y-auto space-y-2">
              {labsArray.map((lab) => {
                const isEnding = lab.status === "ending";
                return (
                  <div
                    key={lab.id}
                    className={`flex items-start space-x-3 p-2 rounded-md ${
                      isEnding ? "bg-yellow-50 dark:bg-yellow-950/30" : "hover:bg-muted/50"
                    }`}
                  >
                    {isEnding ? (
                      <Loader2 className="h-4 w-4 mt-0.5 animate-spin text-yellow-600" />
                    ) : (
                      <Checkbox
                        id={`lab-${lab.id}`}
                        checked={selectedLabIds.has(lab.id)}
                        onCheckedChange={() => toggleLab(lab.id)}
                      />
                    )}
                    <label
                      htmlFor={isEnding ? undefined : `lab-${lab.id}`}
                      className={`flex-1 ${isEnding ? "" : "cursor-pointer"}`}
                    >
                      <div className="text-sm font-medium">{lab.recipe.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {lab.recipe.software}
                        {lab.recipe.exploitFamily && ` - ${lab.recipe.exploitFamily}`}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Started {formatDate(lab.createdAt)} &bull;{" "}
                        {isEnding ? (
                          <span className="text-yellow-600 dark:text-yellow-400 font-medium">
                            Stopping...
                          </span>
                        ) : (
                          <span className="capitalize">{lab.status}</span>
                        )}
                      </div>
                    </label>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={isTerminating}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleTerminate}
            disabled={isTerminating || (noneSelected && selectableLabs.length > 0) || (selectableLabs.length === 0 && endingLabs.length > 0)}
          >
            {isTerminating
              ? "Terminating..."
              : selectableLabs.length === 0 && endingLabs.length > 0
                ? "Waiting for labs to stop..."
                : `Terminate ${selectedLabIds.size} & Create New`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
