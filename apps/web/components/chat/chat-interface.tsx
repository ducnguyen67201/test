'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Send, Loader2, Sparkles, CheckCircle2, XCircle } from 'lucide-react';
import { trpc } from '@/lib/trpc/client';
import type { ChatSession, ChatMessage } from '@/lib/schemas/chat';
import { ChatMessageList } from './chat-message-list';
import { ChatHeader } from './chat-header';

interface ChatInterfaceProps {
  sessionId?: string;
  onSessionCreated?: (session: ChatSession) => void;
  onIntentExtracted?: (intentId: string) => void;
}

export function ChatInterface({
  sessionId: initialSessionId,
  onSessionCreated,
  onIntentExtracted,
}: ChatInterfaceProps) {
  const router = useRouter();
  const [sessionId, setSessionId] = useState<string | undefined>(initialSessionId);
  const [message, setMessage] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Create session mutation
  const createSession = trpc.chat.createSession.useMutation({
    onSuccess: (session) => {
      setSessionId(session.id);
      onSessionCreated?.(session);
    },
  });

  // Get session with messages
  const { data: sessionData, refetch: refetchSession } =
    trpc.chat.getSessionWithMessages.useQuery(
      { sessionId: sessionId! },
      { enabled: !!sessionId, refetchInterval: false }
    );

  // Send message mutation
  const sendMessage = trpc.chat.sendMessage.useMutation({
    onSuccess: () => {
      refetchSession();
      setMessage('');
    },
  });

  // Finalize session mutation
  const finalizeSession = trpc.chat.finalizeSession.useMutation({
    onSuccess: (intent) => {
      console.log('Intent extracted successfully:', intent.id);
      // Call optional callback
      onIntentExtracted?.(intent.id);
      // Redirect to approvals page to review the intent
      router.push('/recipes/approvals');
    },
  });

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [sessionData?.messages, streamingContent]);

  // Initialize session if not provided
  useEffect(() => {
    if (!sessionId && !createSession.isPending) {
      createSession.mutate({});
    }
  }, []);

  const handleSendMessage = async () => {
    if (!message.trim() || !sessionId || isStreaming) return;

    const userMessage = message.trim();
    setMessage('');

    // Use SSE streaming for better UX
    handleStreamMessage(userMessage);
  };

  const handleStreamMessage = async (userMessage: string) => {
    if (!sessionId) return;

    setIsStreaming(true);
    setStreamingContent('');

    try {
      // EventSource doesn't support custom headers, so we fallback to non-streaming
      // for now. In production, you'd implement a different streaming approach
      // or configure backend to accept token via query params
      console.log('Streaming not supported, using non-streaming fallback');
      setIsStreaming(false);
      sendMessage.mutate({ session_id: sessionId, message: userMessage });
      return;

      /* SSE implementation (requires token as query param)
      const eventSource = new EventSource(
        `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions/${sessionId}/stream?message=${encodeURIComponent(
          userMessage
        )}`,
      );

      eventSource.addEventListener('delta', (event) => {
        const data = JSON.parse(event.data);
        setStreamingContent((prev) => prev + (data.content || ''));
      });

      eventSource.addEventListener('done', () => {
        eventSource.close();
        setIsStreaming(false);
        setStreamingContent('');
        refetchSession();
      });

      eventSource.addEventListener('error', (event) => {
        console.error('SSE error:', event);
        eventSource.close();
        setIsStreaming(false);
        setStreamingContent('');
        // Fallback to non-streaming
        sendMessage.mutate({ session_id: sessionId, message: userMessage });
      });

      eventSource.onerror = () => {
        eventSource.close();
        setIsStreaming(false);
        setStreamingContent('');
      };
      */
    } catch (error) {
      console.error('Streaming error:', error);
      setIsStreaming(false);
      // Fallback to non-streaming
      sendMessage.mutate({ session_id: sessionId, message: userMessage });
    }
  };

  const handleFinalize = () => {
    if (!sessionId) return;
    finalizeSession.mutate({ sessionId });
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  if (!sessionId || createSession.isPending) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin" />
            Initializing Chat Session...
          </CardTitle>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className="flex flex-col h-[600px]">
      <ChatHeader
        session={sessionData?.session}
        onFinalize={handleFinalize}
        isFinalizing={finalizeSession.isPending}
      />

      <CardContent className="flex-1 overflow-y-auto p-4 space-y-4">
        <ChatMessageList
          messages={sessionData?.messages || []}
          streamingContent={streamingContent}
          isStreaming={isStreaming}
        />
        <div ref={messagesEndRef} />
      </CardContent>

      {/* Input area */}
      <div className="p-4 border-t">
        <div className="flex gap-2">
          <Input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Describe your testing environment needs..."
            disabled={isStreaming || sendMessage.isPending}
            className="flex-1"
          />
          <Button
            onClick={handleSendMessage}
            disabled={!message.trim() || isStreaming || sendMessage.isPending}
            size="icon"
          >
            {isStreaming || sendMessage.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground mt-2">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </Card>
  );
}
