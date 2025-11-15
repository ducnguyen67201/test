import { ChatInterface } from '@/components/chat/chat-interface';
import { AuthenticatedUser } from '@/components/auth/authenticated-user';

interface ChatPageProps {
  params: Promise<{
    sessionId: string;
  }>;
}

export default async function ChatPage({ params }: ChatPageProps) {
  const { sessionId } = await params;

  return (
    <AuthenticatedUser>
      <div className="container mx-auto py-6">
        <ChatInterface sessionId={sessionId} />
      </div>
    </AuthenticatedUser>
  );
}
