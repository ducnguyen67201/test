"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, ArrowRight, Bot, Terminal, ExternalLink, Square, RotateCw, Loader2 } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { api } from "@/lib/trpc/react";
import { RecipePreview } from "./recipe-preview";
import { QuotaExceededModal, type ActiveLab } from "@/components/quota-exceeded-modal";
import type { RecipeCreate } from "@/lib/schemas/recipe";

/**
 * Lab Status Badge Component
 */
function LabStatusBadge({ labId, status }: { labId: string; status: string }) {
  const utils = api.useUtils();
  const { data: labData, isLoading } = api.lab.getStatus.useQuery(
    { labId },
    { refetchInterval: status === "provisioning" ? 3000 : false }
  );

  const stopMutation = api.lab.stop.useMutation({
    onSuccess: () => utils.lab.getStatus.invalidate({ labId }),
  });
  const restartMutation = api.lab.restart.useMutation({
    onSuccess: () => utils.lab.getStatus.invalidate({ labId }),
  });
  const connectMutation = api.lab.connect.useMutation({
    onSuccess: () => utils.lab.getStatus.invalidate({ labId }),
  });

  const currentStatus = labData?.status ?? status;
  const isActive = ["provisioning", "ready", "connecting", "connected"].includes(currentStatus);
  const isReady = currentStatus === "ready" || currentStatus === "connected";
  const isProvisioning = currentStatus === "provisioning";
  const isStopped = currentStatus === "stopped" || currentStatus === "expired";

  const statusConfig: Record<string, { bg: string; text: string; dot: string; label: string }> = {
    provisioning: { bg: "bg-yellow-50 dark:bg-yellow-950", text: "text-yellow-700 dark:text-yellow-300", dot: "bg-yellow-500", label: "Deploying" },
    ready: { bg: "bg-green-50 dark:bg-green-950", text: "text-green-700 dark:text-green-300", dot: "bg-green-500", label: "Ready" },
    connecting: { bg: "bg-blue-50 dark:bg-blue-950", text: "text-blue-700 dark:text-blue-300", dot: "bg-blue-500", label: "Connecting" },
    connected: { bg: "bg-green-50 dark:bg-green-950", text: "text-green-700 dark:text-green-300", dot: "bg-green-500", label: "Connected" },
    stopped: { bg: "bg-gray-50 dark:bg-gray-900", text: "text-gray-600 dark:text-gray-400", dot: "bg-gray-400", label: "Stopped" },
    expired: { bg: "bg-red-50 dark:bg-red-950", text: "text-red-700 dark:text-red-300", dot: "bg-red-500", label: "Expired" },
    error: { bg: "bg-red-50 dark:bg-red-950", text: "text-red-700 dark:text-red-300", dot: "bg-red-500", label: "Error" },
  };

  const config = statusConfig[currentStatus] ?? statusConfig.error;

  const handleConnect = () => {
    // Use our API proxy route which handles authentication with the backend
    window.open(`/api/labs/${labId}/connect`, "_blank");
  };

  return (
    <div className={cn("mt-3 rounded-lg border p-3", config.bg)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={cn("h-2 w-2 rounded-full", config.dot, isProvisioning && "animate-pulse")} />
          <span className={cn("text-sm font-medium", config.text)}>
            Lab {config.label}
          </span>
          <code className="text-xs text-muted-foreground">
            {labId.slice(0, 8)}...
          </code>
        </div>
      </div>

      {/* Action buttons */}
      <div className="mt-2 flex flex-wrap gap-2">
        {isReady && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={handleConnect}
            disabled={connectMutation.isPending}
          >
            {connectMutation.isPending ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <ExternalLink className="mr-1 h-3 w-3" />
            )}
            Connect
          </Button>
        )}

        {isActive && !isProvisioning && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => stopMutation.mutate({ labId })}
            disabled={stopMutation.isPending}
          >
            {stopMutation.isPending ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <Square className="mr-1 h-3 w-3" />
            )}
            Stop
          </Button>
        )}

        {isStopped && currentStatus !== "expired" && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => restartMutation.mutate({ labId })}
            disabled={restartMutation.isPending}
          >
            {restartMutation.isPending ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <RotateCw className="mr-1 h-3 w-3" />
            )}
            Restart
          </Button>
        )}

        {isProvisioning && (
          <span className="flex items-center text-xs text-muted-foreground">
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            Setting up environment...
          </span>
        )}
      </div>

      {/* Connection URL if available */}
      {isReady && (
        <div className="mt-2 text-xs text-muted-foreground">
          <span className="font-medium">Lab Page: </span>
          <a
            href={`/api/labs/${labId}/connect`}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline text-orange-600"
          >
            Open in OctoLab
          </a>
        </div>
      )}

      {/* Recipe info */}
      {labData?.recipe && (
        <div className="mt-2 pt-2 border-t border-dashed text-xs text-muted-foreground">
          <span className="font-medium">{labData.recipe.name}</span>
          <span className="mx-1">•</span>
          <span>{labData.recipe.software}</span>
        </div>
      )}
    </div>
  );
}

type RecipeData = {
  name: string;
  description: string;
  software: string;
  version_constraint?: string | null;
  exploit_family?: string | null;
  is_active?: boolean;
};

interface Message {
  id: string;
  role: "assistant" | "user";
  content: string;
  timestamp: string;
  suggestions?: string[];
  recipe?: RecipeData | null;
  labId?: string;
  labStatus?: string;
}

const welcomeMessage: Message = {
  id: "welcome",
  role: "assistant",
  content:
    "Welcome to OctoLab! I can help you set up vulnerability lab environments for penetration testing practice. Describe the CVE, software, or attack scenario you want to rehearse, and I'll generate the appropriate lab configuration.\n\nFor example:\n• 'I need to practice Apache path traversal CVE-2021-41773'\n• 'Set up a Log4Shell lab'\n• 'I want to test SQL injection attacks'",
  timestamp: "Just now",
  suggestions: [
    "Apache CVE-2021-41773",
    "Log4Shell (CVE-2021-44228)",
    "SQL Injection basics",
    "Java deserialization",
  ],
};

interface ChatbotPanelProps {
  sessionId?: string | null;
  onSessionCreated?: (sessionId: string) => void;
}

export function ChatbotPanel({ sessionId, onSessionCreated }: ChatbotPanelProps) {
  const [messages, setMessages] = useState<Message[]>([welcomeMessage]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [deployingRecipe, setDeployingRecipe] = useState<string | null>(null);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(sessionId ?? null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Quota exceeded modal state
  const [showQuotaModal, setShowQuotaModal] = useState(false);
  const [activeLabs, setActiveLabs] = useState<ActiveLab[]>([]);
  const [isTerminating, setIsTerminating] = useState(false);
  const [terminationProgress, setTerminationProgress] = useState(0);
  const [terminationStatus, setTerminationStatus] = useState("");
  const [pendingRecipe, setPendingRecipe] = useState<{ recipe: RecipeData; messageId: string } | null>(null);
  const [generatingRecipe, setGeneratingRecipe] = useState<string | null>(null);
  const [recipesWithDockerfile, setRecipesWithDockerfile] = useState<Set<string>>(new Set());

  const chatMutation = api.recipe.chat.useMutation();
  const deployMutation = api.recipe.deploy.useMutation();
  const createRecipeMutation = api.recipe.createRecipe.useMutation();
  const generateDockerfileMutation = api.recipe.generateDockerfile.useMutation();
  const createSessionMutation = api.chat.createSession.useMutation();
  const addMessageMutation = api.chat.addMessage.useMutation();
  const generateTitleMutation = api.chat.generateTitle.useMutation();
  const labConnectMutation = api.lab.connect.useMutation();
  const stopLabMutation = api.lab.stop.useMutation();

  // Load existing session messages
  const { data: sessionData } = api.chat.getSession.useQuery(
    { sessionId: sessionId! },
    { enabled: !!sessionId }
  );

  // Load session messages when sessionData changes
  useEffect(() => {
    if (sessionData?.messages && sessionData.messages.length > 0) {
      const loadedMessages: Message[] = sessionData.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: new Date(m.createdAt).toLocaleTimeString(),
        suggestions: (m.metadata as { suggestions?: string[] })?.suggestions,
        recipe: (m.metadata as { recipe?: RecipeData })?.recipe,
        labId: (m.metadata as { labId?: string })?.labId,
        labStatus: (m.metadata as { labStatus?: string })?.labStatus,
      }));
      setMessages([welcomeMessage, ...loadedMessages]);
      setCurrentSessionId(sessionData.id);
    }
  }, [sessionData]);

  // Reset when sessionId changes to null (new chat)
  useEffect(() => {
    if (sessionId === null) {
      setMessages([welcomeMessage]);
      setCurrentSessionId(null);
      setConversationId(null);
    }
  }, [sessionId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const ensureSession = async (): Promise<string> => {
    if (currentSessionId) return currentSessionId;

    const session = await createSessionMutation.mutateAsync({});
    setCurrentSessionId(session.id);
    onSessionCreated?.(session.id);
    return session.id;
  };

  const handleSend = async () => {
    if (!input.trim() || isTyping) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
      timestamp: "Just now",
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsTyping(true);

    // Ensure we have a session
    const activeSessionId = await ensureSession();

    // Save user message to database
    await addMessageMutation.mutateAsync({
      sessionId: activeSessionId,
      role: "user",
      content: input,
    });

    // Generate title from first message
    if (messages.length === 1) {
      generateTitleMutation.mutate({ sessionId: activeSessionId });
    }

    // Add typing indicator
    const typingId = (Date.now() + 1).toString();
    setMessages((prev) => [
      ...prev,
      {
        id: typingId,
        role: "assistant",
        content: "",
        timestamp: "Just now",
      },
    ]);

    try {
      const response = await chatMutation.mutateAsync({
        message: input,
        conversationId: conversationId ?? undefined,
      });

      // Store conversation ID for multi-turn context
      if (response.conversationId) {
        setConversationId(response.conversationId);
      }

      const metadata: Record<string, unknown> = {};
      if (response.suggestions?.length) {
        metadata.suggestions = response.suggestions;
      }
      if (response.recipe) {
        metadata.recipe = response.recipe;
      }

      // Save assistant message to database
      await addMessageMutation.mutateAsync({
        sessionId: activeSessionId,
        role: "assistant",
        content: response.message,
        metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
      });

      // Replace typing indicator with actual response
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === typingId
            ? {
                ...msg,
                content: response.message,
                suggestions: response.suggestions ?? [],
                recipe: response.recipe,
              }
            : msg
        )
      );
    } catch (_error) {
      // Replace typing indicator with error message
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === typingId
            ? {
                ...msg,
                content:
                  "Sorry, I encountered an error processing your request. Please try again.",
              }
            : msg
        )
      );
    } finally {
      setIsTyping(false);
    }
  };

  const handleGenerateDockerfile = async (recipe: RecipeData, messageId: string) => {
    setGeneratingRecipe(messageId);

    try {
      // First create the recipe in the database (without deploying)
      const createResult = await createRecipeMutation.mutateAsync(recipe as RecipeCreate);

      // If recipe already has dockerfile, mark it and skip generation
      if (createResult.hasDockerfile) {
        setRecipesWithDockerfile((prev) => new Set(prev).add(recipe.name));
        const alreadyMessage: Message = {
          id: Date.now().toString(),
          role: "assistant",
          content: "Dockerfile already exists for this recipe. You can deploy the lab now.",
          timestamp: "Just now",
        };
        setMessages((prev) => [...prev, alreadyMessage]);
        return;
      }

      // Generate dockerfile for the recipe
      const result = await generateDockerfileMutation.mutateAsync({ recipeId: createResult.id });

      if (result.success) {
        // Mark this recipe as having a dockerfile
        setRecipesWithDockerfile((prev) => new Set(prev).add(recipe.name));

        // Add a success message
        const genMessage: Message = {
          id: Date.now().toString(),
          role: "assistant",
          content: result.fromCache
            ? `Dockerfile ready! Found a cached version for this CVE. You can now deploy the lab.`
            : `Dockerfile generated successfully! ${result.vulnerabilityNotes ? `\n\n**Exploit tip:** ${result.vulnerabilityNotes}` : ""}\n\nYou can now deploy the lab environment.`,
          timestamp: "Just now",
        };
        setMessages((prev) => [...prev, genMessage]);

        // Save to database if we have a session
        if (currentSessionId) {
          await addMessageMutation.mutateAsync({
            sessionId: currentSessionId,
            role: "assistant",
            content: genMessage.content,
            metadata: {},
          });
        }
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Failed to generate Dockerfile";
      console.error("[generateDockerfile] Error:", errorMessage);

      // Show error message
      const errMessage: Message = {
        id: Date.now().toString(),
        role: "assistant",
        content: `Failed to generate Dockerfile: ${errorMessage}. Please try again or contact support.`,
        timestamp: "Just now",
      };
      setMessages((prev) => [...prev, errMessage]);
    } finally {
      setGeneratingRecipe(null);
    }
  };

  const handleDeploy = async (recipe: RecipeData, messageId: string) => {
    setDeployingRecipe(messageId);

    try {
      // Cast to RecipeCreate for the mutation (data matches schema)
      const result = await deployMutation.mutateAsync(recipe as RecipeCreate);

      // Add deployment confirmation message
      const deployMessage: Message = {
        id: Date.now().toString(),
        role: "assistant",
        content: result.message,
        timestamp: "Just now",
        labId: result.lab.id,
        labStatus: result.lab.status,
        suggestions: ["Check lab status", "Connect to lab", "Start another lab"],
      };

      setMessages((prev) => [...prev, deployMessage]);

      // Save to database if we have a session
      if (currentSessionId) {
        await addMessageMutation.mutateAsync({
          sessionId: currentSessionId,
          role: "assistant",
          content: result.message,
          metadata: {
            labId: result.lab.id,
            labStatus: result.lab.status,
            suggestions: ["Check lab status", "Connect to lab", "Start another lab"],
          },
        });
      }
    } catch (error) {
      // Check if it's a quota exceeded error (TOO_MANY_REQUESTS)
      const trpcError = error as { data?: { code?: string }; message?: string };
      console.log("[QuotaDebug] Error caught:", trpcError.data?.code);

      if (trpcError.data?.code === "TOO_MANY_REQUESTS") {
        console.log("[QuotaDebug] 429 detected, fetching active labs...");
        // Fetch active labs and show modal
        try {
          const response = await fetch("/api/trpc/lab.listActive", {
            method: "GET",
            credentials: "include",
          });
          console.log("[QuotaDebug] listActive response status:", response.status);
          const data = await response.json();
          console.log("[QuotaDebug] listActive raw data:", data);
          // tRPC single procedure returns: {result: {data: {json: [...]}}}
          // tRPC batch returns: [{result: {data: {json: [...]}}}]
          const resultData = Array.isArray(data)
            ? data[0]?.result?.data
            : data?.result?.data;
          // Handle both {json: [...]} wrapper and direct array
          const labs = resultData?.json ?? resultData;
          console.log("[QuotaDebug] Extracted labs:", labs);
          if (Array.isArray(labs)) {
            setActiveLabs(labs as ActiveLab[]);
          } else {
            setActiveLabs([]);
          }
        } catch (fetchError) {
          console.log("[QuotaDebug] listActive fetch error:", fetchError);
          // Fallback: empty list, user can still cancel
          setActiveLabs([]);
        }
        console.log("[QuotaDebug] Showing modal...");
        setPendingRecipe({ recipe, messageId });
        setShowQuotaModal(true);
        return; // Don't show error message, modal handles it
      }

      const errorMessage: Message = {
        id: Date.now().toString(),
        role: "assistant",
        content:
          "Failed to deploy the lab. Please try again or contact support if the issue persists.",
        timestamp: "Just now",
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setDeployingRecipe(null);
    }
  };

  // Handle termination of labs and retry deploy
  const handleTerminateAndRetry = useCallback(async (labIds: string[]) => {
    if (!pendingRecipe) return;

    setIsTerminating(true);
    setTerminationProgress(0);

    try {
      // Stop each lab - lab.stop now handles polling until terminal state internally
      for (let i = 0; i < labIds.length; i++) {
        const labId = labIds[i];
        setTerminationStatus(`Stopping lab ${i + 1} of ${labIds.length}...`);

        // Stop the lab - this now polls until FINISHED/FAILED state with 60s timeout
        const result = await stopLabMutation.mutateAsync({ labId });

        // Check if stop succeeded
        if (!result.success) {
          console.warn(`Lab ${labId} stop returned: ${result.message}`);
          // Continue to next lab - it may already be stopped
        }

        setTerminationProgress(((i + 1) / labIds.length) * 80); // 80% for termination
      }

      setTerminationStatus("Deploying new lab...");
      setTerminationProgress(90);

      // Retry deploy
      const { recipe, messageId } = pendingRecipe;
      setShowQuotaModal(false);
      setPendingRecipe(null);
      setIsTerminating(false);
      setTerminationProgress(0);
      setTerminationStatus("");

      // Small delay to let backend process the terminations
      await new Promise((resolve) => setTimeout(resolve, 1000));

      // Retry the deploy
      await handleDeploy(recipe, messageId);
    } catch (error) {
      console.error("Failed to terminate labs:", error);
      setTerminationStatus("Failed to terminate labs. Please try again.");
      setIsTerminating(false);
    }
  }, [pendingRecipe, stopLabMutation]);

  const handleQuotaModalCancel = useCallback(() => {
    setShowQuotaModal(false);
    setPendingRecipe(null);
    setActiveLabs([]);

    // Show a message that deploy was cancelled
    const cancelMessage: Message = {
      id: Date.now().toString(),
      role: "assistant",
      content: "Lab deployment cancelled. You've reached your lab quota. Terminate existing labs from the Labs page to create new ones.",
      timestamp: "Just now",
      suggestions: ["View my labs", "Start another lab"],
    };
    setMessages((prev) => [...prev, cancelMessage]);
  }, []);

  const handleSuggestionClick = async (suggestion: string, labId?: string) => {
    // Handle lab-related suggestions
    if (suggestion === "Check lab status" && labId) {
      setInput(`Check the status of my lab ${labId.slice(0, 8)}`);
      return;
    }

    if (suggestion === "Connect to lab" && labId) {
      try {
        const result = await labConnectMutation.mutateAsync({ labId });
        const connectMessage: Message = {
          id: Date.now().toString(),
          role: "assistant",
          content: `${result.message}\n\nConnection URL: ${result.connectionUrl}\n\nYou can access your lab environment through the web terminal or SSH.`,
          timestamp: "Just now",
          labId: result.labId,
          labStatus: result.status,
          suggestions: ["Open web terminal", "View lab details", "Start another lab"],
        };
        setMessages((prev) => [...prev, connectMessage]);

        // Save to database if we have a session
        if (currentSessionId) {
          await addMessageMutation.mutateAsync({
            sessionId: currentSessionId,
            role: "assistant",
            content: connectMessage.content,
            metadata: {
              labId: result.labId,
              labStatus: result.status,
              connectionUrl: result.connectionUrl,
              suggestions: connectMessage.suggestions,
            },
          });
        }
      } catch (error) {
        const errorMessage: Message = {
          id: Date.now().toString(),
          role: "assistant",
          content: `Failed to connect to lab: ${error instanceof Error ? error.message : "Unknown error"}`,
          timestamp: "Just now",
        };
        setMessages((prev) => [...prev, errorMessage]);
      }
      return;
    }

    if (suggestion === "Open web terminal" && labId) {
      window.open(`https://terminal.octolab.dev/${labId}`, "_blank");
      return;
    }

    // Default: set as input for regular suggestions
    setInput(suggestion);
  };

  return (
    <div className="flex h-full flex-col rounded-xl border bg-card">
      {/* Header */}
      <div className="border-b px-6 py-4">
        <div className="flex items-center gap-2">
          <Terminal className="h-5 w-5 text-orange-500" />
          <h2 className="text-lg font-semibold">OctoLab Assistant</h2>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          CVE Lab Environment Generator
        </p>
      </div>

      {/* Messages */}
      <ScrollArea className="flex-1 p-6" ref={scrollRef}>
        <div className="space-y-6">
          {messages.map((message) => (
            <div key={message.id}>
              {/* Message */}
              <div className="flex gap-3">
                <Avatar className="h-9 w-9">
                  {message.role === "assistant" ? (
                    <>
                      <AvatarImage src="/octolab-ai.png" />
                      <AvatarFallback className="bg-orange-100 text-orange-600 text-xs">
                        <Bot className="h-4 w-4" />
                      </AvatarFallback>
                    </>
                  ) : (
                    <>
                      <AvatarImage src="/user-avatar.png" />
                      <AvatarFallback className="bg-blue-100 text-blue-600 text-xs">
                        U
                      </AvatarFallback>
                    </>
                  )}
                </Avatar>
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">
                      {message.role === "assistant" ? "OctoLab AI" : "You"}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {message.timestamp}
                    </span>
                  </div>
                  {message.content ? (
                    <p className="mt-1 text-sm text-muted-foreground leading-relaxed whitespace-pre-line">
                      {message.content}
                    </p>
                  ) : isTyping && message.role === "assistant" ? (
                    <div className="mt-2 flex items-center gap-1">
                      <span
                        className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40"
                        style={{ animationDelay: "0ms" }}
                      />
                      <span
                        className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40"
                        style={{ animationDelay: "150ms" }}
                      />
                      <span
                        className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40"
                        style={{ animationDelay: "300ms" }}
                      />
                    </div>
                  ) : null}

                  {/* Lab Status */}
                  {message.labId && message.labStatus && (
                    <LabStatusBadge
                      labId={message.labId}
                      status={message.labStatus}
                    />
                  )}
                </div>
              </div>

              {/* Recipe Preview */}
              {message.recipe && (
                <div className="mt-4 ml-12">
                  <RecipePreview
                    recipe={message.recipe}
                    onDeploy={() => handleDeploy(message.recipe!, message.id)}
                    isDeploying={deployingRecipe === message.id}
                    onGenerateDockerfile={() => handleGenerateDockerfile(message.recipe!, message.id)}
                    isGenerating={generatingRecipe === message.id}
                    hasDockerfile={recipesWithDockerfile.has(message.recipe.name)}
                  />
                </div>
              )}

              {/* Suggestions */}
              {message.suggestions && message.suggestions.length > 0 && (
                <div className="mt-4 ml-12 rounded-lg border bg-muted/30 p-4">
                  <p className="text-sm font-medium text-muted-foreground">
                    Suggestions:
                  </p>
                  <div className="mt-3 space-y-2">
                    {message.suggestions.map((suggestion, index) => (
                      <button
                        key={index}
                        onClick={() => handleSuggestionClick(suggestion, message.labId)}
                        className="flex w-full items-center justify-between text-left text-sm hover:text-orange-600 transition-colors"
                      >
                        <span>{suggestion}</span>
                        <ArrowRight className="h-4 w-4" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>

      {/* Input */}
      <div className="border-t p-4">
        <div className="flex items-center gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            placeholder="Describe the CVE or vulnerability scenario..."
            className="flex-1 border-muted-foreground/20"
            disabled={isTyping}
          />
          <Button
            onClick={handleSend}
            size="icon"
            disabled={isTyping || !input.trim()}
            className={cn(
              "h-10 w-10 rounded-lg",
              input.trim() && !isTyping
                ? "bg-orange-500 hover:bg-orange-600"
                : "bg-muted"
            )}
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Quota Exceeded Modal */}
      <QuotaExceededModal
        isOpen={showQuotaModal}
        activeLabs={activeLabs}
        onTerminateAndRetry={handleTerminateAndRetry}
        onCancel={handleQuotaModalCancel}
        isTerminating={isTerminating}
        terminationProgress={terminationProgress}
        terminationStatus={terminationStatus}
      />
    </div>
  );
}
