'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import { RecipeDetail } from '@/components/recipes/recipe-detail';
import { Button } from '@/components/ui/button';
import { ArrowLeft } from 'lucide-react';

interface RecipeDetailPageProps {
  params: Promise<{
    recipeId: string;
  }>;
}

export default function RecipeDetailPage({ params }: RecipeDetailPageProps) {
  const router = useRouter();
  const unwrappedParams = React.use(params);
  const { recipeId } = unwrappedParams;

  const handleClose = () => {
    router.push('/recipes');
  };

  return (
    <div className="container mx-auto py-6">
      <div className="mb-4">
        <Button variant="ghost" onClick={handleClose}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Recipes
        </Button>
      </div>
      <RecipeDetail recipeId={recipeId} onClose={handleClose} />
    </div>
  );
}
