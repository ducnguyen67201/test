"use client";

import { useState } from "react";
import { MessageSquare, Plus, Trash2, MoreHorizontal, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import { api } from "@/lib/trpc/react";
import { formatDistanceToNow } from "date-fns";

interface ChatHistoryProps {
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string | null) => void;
  onNewChat: () => void;
}

export function ChatHistory({
  selectedSessionId,
  onSelectSession,
  onNewChat,
}: ChatHistoryProps) {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);

  const { data, isLoading, refetch } = api.chat.listSessions.useQuery({
    limit: 30,
  });

  const deleteSessionMutation = api.chat.deleteSession.useMutation({
    onSuccess: () => {
      refetch();
      if (selectedSessionId === deletingId) {
        onSelectSession(null);
      }
      setDeletingId(null);
    },
  });

  const clearAllMutation = api.chat.clearAllHistory.useMutation({
    onSuccess: () => {
      refetch();
      onSelectSession(null);
      setClearDialogOpen(false);
    },
  });

  const handleDelete = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeletingId(sessionId);
    deleteSessionMutation.mutate({ sessionId });
  };

  const handleClearAll = () => {
    clearAllMutation.mutate();
  };

  return (
    <div className="flex h-full flex-col rounded-xl border bg-card">
      {/* Header */}
      <div className="border-b px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">Chat History</h3>
          <div className="flex items-center gap-1">
            {data?.sessions && data.sessions.length > 0 && (
              <AlertDialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    title="Clear all chats"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Clear all chat history?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This will permanently delete all {data.sessions.length} chat sessions and their messages. This action cannot be undone.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={handleClearAll}
                      className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      disabled={clearAllMutation.isPending}
                    >
                      {clearAllMutation.isPending ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Clearing...
                        </>
                      ) : (
                        "Clear All"
                      )}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={onNewChat}
              className="h-8 w-8"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* Chat List */}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {isLoading ? (
            <div className="p-4 text-center text-sm text-muted-foreground">
              Loading...
            </div>
          ) : data?.sessions.length === 0 ? (
            <div className="p-4 text-center text-sm text-muted-foreground">
              No chat history yet.
              <br />
              Start a new conversation!
            </div>
          ) : (
            data?.sessions.map((session) => (
              <div
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={cn(
                  "group flex items-start gap-2 rounded-lg p-2 cursor-pointer transition-colors",
                  selectedSessionId === session.id
                    ? "bg-orange-100 dark:bg-orange-950"
                    : "hover:bg-muted"
                )}
              >
                <MessageSquare className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{session.title}</p>
                  {session.preview && (
                    <p className="text-xs text-muted-foreground truncate">
                      {session.preview}
                    </p>
                  )}
                  <p className="text-[10px] text-muted-foreground mt-1">
                    {formatDistanceToNow(new Date(session.updatedAt), {
                      addSuffix: true,
                    })}
                  </p>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 opacity-0 group-hover:opacity-100"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <MoreHorizontal className="h-3 w-3" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      onClick={(e) => handleDelete(session.id, e)}
                      className="text-destructive"
                      disabled={deletingId === session.id}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      {deletingId === session.id ? "Deleting..." : "Delete"}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))
          )}
        </div>
      </ScrollArea>

      {/* New Chat Button */}
      <div className="border-t p-2">
        <Button
          variant="outline"
          className="w-full justify-start gap-2"
          onClick={onNewChat}
        >
          <Plus className="h-4 w-4" />
          New Chat
        </Button>
      </div>
    </div>
  );
}
