'use client';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { User, Bot, Terminal } from 'lucide-react';
import type { ChatMessage } from '@/lib/schemas/chat';
import { cn } from '@/lib/utils';

interface ChatMessageListProps {
  messages: ChatMessage[];
  streamingContent?: string;
  isStreaming?: boolean;
}

export function ChatMessageList({
  messages,
  streamingContent,
  isStreaming,
}: ChatMessageListProps) {
  return (
    <>
      {messages.map((message) => (
        <ChatMessageBubble key={message.id} message={message} />
      ))}
      {isStreaming && streamingContent && (
        <ChatMessageBubble
          message={{
            id: 'streaming',
            session_id: '',
            role: 'assistant',
            content: streamingContent,
            sequence: 0,
            tokens: 0,
            created_at: new Date().toISOString(),
          }}
          isStreaming
        />
      )}
    </>
  );
}

interface ChatMessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

function ChatMessageBubble({ message, isStreaming }: ChatMessageBubbleProps) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  // Don't show system messages
  if (isSystem) return null;

  return (
    <div
      className={cn(
        'flex gap-3 items-start',
        isUser && 'flex-row-reverse'
      )}
    >
      <Avatar className="h-8 w-8">
        <AvatarFallback className={isUser ? 'bg-primary' : 'bg-secondary'}>
          {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
        </AvatarFallback>
      </Avatar>

      <div
        className={cn(
          'flex flex-col gap-1 max-w-[80%]',
          isUser && 'items-end'
        )}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">
            {isUser ? 'You' : 'Assistant'}
          </span>
          {isStreaming && (
            <Badge variant="outline" className="text-xs">
              Typing...
            </Badge>
          )}
        </div>

        <div
          className={cn(
            'rounded-lg px-4 py-2 text-sm whitespace-pre-wrap',
            isUser
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted'
          )}
        >
          {message.content}
          {isStreaming && <span className="inline-block w-2 h-4 bg-current animate-pulse ml-1" />}
        </div>

        <span className="text-xs text-muted-foreground">
          {new Date(message.created_at).toLocaleTimeString()}
          {message.tokens > 0 && ` • ${message.tokens} tokens`}
        </span>
      </div>
    </div>
  );
}
