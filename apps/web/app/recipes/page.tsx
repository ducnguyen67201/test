'use client';

import { useRouter } from 'next/navigation';
import { RecipeDashboard } from '@/components/recipes/recipe-dashboard';
import { trpc } from '@/lib/trpc/client';

export default function RecipesPage() {
  const router = useRouter();

  // Create new chat session
  const createSession = trpc.chat.createSession.useMutation({
    onSuccess: (data) => {
      console.log('Chat session created:', data);
      router.push(`/recipes/chat/${data.session.id}`);
    },
    onError: (error) => {
      console.error('Failed to create chat session:', error);
      alert('Failed to create chat session: ' + error.message);
    },
  });

  const handleCreateNew = () => {
    console.log('Create Recipe button clicked');
    createSession.mutate({});
  };

  const handleRecipeClick = (recipeId: string) => {
    router.push(`/recipes/${recipeId}`);
  };

  return (
    <div className="container mx-auto py-6">
      <RecipeDashboard onCreateNew={handleCreateNew} onRecipeClick={handleRecipeClick} />
    </div>
  );
}
