"use client";

import { useState, useRef, useEffect } from "react";
import { usePathname } from "next/navigation";
import {
  MessageSquarePlus,
  X,
  Bug,
  Lightbulb,
  TrendingUp,
  HelpCircle,
  Star,
  Send,
  GripVertical,
  Check,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { api } from "@/lib/trpc/react";

type FeedbackType = "bug" | "feature" | "improvement" | "other";

interface FeedbackTypeOption {
  value: FeedbackType;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
}

const feedbackTypes: FeedbackTypeOption[] = [
  { value: "bug", label: "Bug", icon: Bug, color: "text-red-500" },
  { value: "feature", label: "Feature", icon: Lightbulb, color: "text-yellow-500" },
  { value: "improvement", label: "Improve", icon: TrendingUp, color: "text-blue-500" },
  { value: "other", label: "Other", icon: HelpCircle, color: "text-gray-500" },
];

interface Position {
  x: number;
  y: number;
}

export function FeedbackWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [feedbackType, setFeedbackType] = useState<FeedbackType | null>(null);
  const [message, setMessage] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const [hoveredRating, setHoveredRating] = useState<number | null>(null);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [position, setPosition] = useState<Position>({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<HTMLDivElement>(null);
  const dragStartPos = useRef<Position>({ x: 0, y: 0 });
  const pathname = usePathname();

  const submitFeedback = api.feedback.submit.useMutation({
    onSuccess: () => {
      setError(null);
      setIsSubmitted(true);
      setTimeout(() => {
        setIsOpen(false);
        setIsSubmitted(false);
        setFeedbackType(null);
        setMessage("");
        setRating(null);
      }, 2000);
    },
    onError: (err) => {
      setError(err.message || "Failed to submit feedback. Please try again.");
    },
  });

  // Load saved position from localStorage
  useEffect(() => {
    const savedPosition = localStorage.getItem("feedbackWidgetPosition");
    if (savedPosition) {
      try {
        setPosition(JSON.parse(savedPosition));
      } catch {
        // Invalid JSON, use default
      }
    }
  }, []);

  // Save position to localStorage
  useEffect(() => {
    if (position.x !== 0 || position.y !== 0) {
      localStorage.setItem("feedbackWidgetPosition", JSON.stringify(position));
    }
  }, [position]);

  const handleDragStart = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("[data-no-drag]")) return;

    setIsDragging(true);
    dragStartPos.current = {
      x: e.clientX - position.x,
      y: e.clientY - position.y,
    };
  };

  const handleDragMove = (e: MouseEvent) => {
    if (!isDragging) return;

    const newX = e.clientX - dragStartPos.current.x;
    const newY = e.clientY - dragStartPos.current.y;

    // Constrain to viewport
    const maxX = window.innerWidth - (dragRef.current?.offsetWidth ?? 0);
    const maxY = window.innerHeight - (dragRef.current?.offsetHeight ?? 0);

    setPosition({
      x: Math.min(Math.max(0, newX), maxX),
      y: Math.min(Math.max(0, newY), maxY),
    });
  };

  const handleDragEnd = () => {
    setIsDragging(false);
  };

  useEffect(() => {
    if (isDragging) {
      document.addEventListener("mousemove", handleDragMove);
      document.addEventListener("mouseup", handleDragEnd);
      return () => {
        document.removeEventListener("mousemove", handleDragMove);
        document.removeEventListener("mouseup", handleDragEnd);
      };
    }
  }, [isDragging]);

  const handleSubmit = () => {
    if (!feedbackType || !message.trim()) return;

    setError(null);
    submitFeedback.mutate({
      type: feedbackType,
      message: message.trim(),
      rating: rating ?? undefined,
      page: pathname,
      metadata: {
        userAgent: typeof window !== "undefined" ? navigator.userAgent : undefined,
        screenWidth: typeof window !== "undefined" ? window.innerWidth : undefined,
        screenHeight: typeof window !== "undefined" ? window.innerHeight : undefined,
      },
    });
  };

  const canSubmit = feedbackType && message.trim().length >= 10;

  return (
    <div
      ref={dragRef}
      className="fixed z-50"
      style={{
        right: position.x === 0 ? "24px" : "auto",
        bottom: position.y === 0 ? "24px" : "auto",
        left: position.x !== 0 ? `${position.x}px` : "auto",
        top: position.y !== 0 ? `${position.y}px` : "auto",
      }}
    >
      {/* Feedback Button */}
      {!isOpen && (
        <Button
          onClick={() => setIsOpen(true)}
          size="lg"
          className="rounded-full h-14 w-14 shadow-lg bg-primary hover:bg-primary/90"
        >
          <MessageSquarePlus className="h-6 w-6" />
        </Button>
      )}

      {/* Feedback Panel */}
      {isOpen && (
        <div
          className={cn(
            "w-[340px] rounded-xl border bg-card shadow-2xl overflow-hidden",
            isDragging && "cursor-grabbing select-none"
          )}
          onMouseDown={handleDragStart}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 bg-muted/50 border-b cursor-grab">
            <div className="flex items-center gap-2">
              <GripVertical className="h-4 w-4 text-muted-foreground" />
              <span className="font-semibold text-sm">Send Feedback</span>
            </div>
            <button
              data-no-drag
              onClick={() => setIsOpen(false)}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Content */}
          <div className="p-4" data-no-drag>
            {isSubmitted ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <div className="h-12 w-12 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center mb-3">
                  <Check className="h-6 w-6 text-green-600 dark:text-green-400" />
                </div>
                <h3 className="font-semibold text-lg">Thank you!</h3>
                <p className="text-sm text-muted-foreground mt-1">
                  Your feedback has been submitted.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Feedback Type */}
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">
                    What type of feedback?
                  </Label>
                  <div className="grid grid-cols-4 gap-2">
                    {feedbackTypes.map((type) => (
                      <button
                        key={type.value}
                        onClick={() => setFeedbackType(type.value)}
                        className={cn(
                          "flex flex-col items-center gap-1 p-2 rounded-lg border transition-all",
                          feedbackType === type.value
                            ? "border-primary bg-primary/10"
                            : "border-transparent hover:bg-muted"
                        )}
                      >
                        <type.icon className={cn("h-5 w-5", type.color)} />
                        <span className="text-xs">{type.label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Message */}
                <div className="space-y-2">
                  <Label htmlFor="feedback-message" className="text-xs text-muted-foreground">
                    Your feedback
                  </Label>
                  <Textarea
                    id="feedback-message"
                    placeholder="Tell us what's on your mind... (min 10 characters)"
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    className="min-h-[100px] resize-none text-sm"
                  />
                  <p className="text-xs text-muted-foreground text-right">
                    {message.length}/2000
                  </p>
                </div>

                {/* Rating */}
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">
                    How would you rate your experience? (optional)
                  </Label>
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <button
                        key={star}
                        onClick={() => setRating(star)}
                        onMouseEnter={() => setHoveredRating(star)}
                        onMouseLeave={() => setHoveredRating(null)}
                        className="p-1 transition-transform hover:scale-110"
                      >
                        <Star
                          className={cn(
                            "h-6 w-6 transition-colors",
                            (hoveredRating !== null ? star <= hoveredRating : star <= (rating ?? 0))
                              ? "fill-yellow-400 text-yellow-400"
                              : "text-muted-foreground/30"
                          )}
                        />
                      </button>
                    ))}
                  </div>
                </div>

                {/* Error Message */}
                {error && (
                  <div className="p-2 rounded-md bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-xs">
                    {error}
                  </div>
                )}

                {/* Submit */}
                <Button
                  onClick={handleSubmit}
                  disabled={!canSubmit || submitFeedback.isPending}
                  className="w-full"
                >
                  {submitFeedback.isPending ? (
                    "Sending..."
                  ) : (
                    <>
                      <Send className="h-4 w-4 mr-2" />
                      Send Feedback
                    </>
                  )}
                </Button>

                <p className="text-xs text-center text-muted-foreground">
                  Your feedback helps us improve OctoLab
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
