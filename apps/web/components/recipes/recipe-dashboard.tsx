'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Search, Plus, Filter } from 'lucide-react';
import { trpc } from '@/lib/trpc/client';
import { RecipeCard } from './recipe-card';
import { Skeleton } from '@/components/ui/skeleton';

interface RecipeDashboardProps {
  onCreateNew?: () => void;
  onRecipeClick?: (recipeId: string) => void;
}

export function RecipeDashboard({ onCreateNew, onRecipeClick }: RecipeDashboardProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [softwareFilter, setSoftwareFilter] = useState<string>('all');
  const [isSearching, setIsSearching] = useState(false);

  // List recipes with filters
  const { data: recipeList, isLoading: isLoadingList } = trpc.recipe.list.useQuery(
    {
      software: softwareFilter !== 'all' ? softwareFilter : undefined,
      limit: 20,
      offset: 0,
    },
    {
      enabled: !isSearching && !searchQuery,
    }
  );

  // Search recipes
  const { data: searchResults, isLoading: isSearchLoading } =
    trpc.recipe.search.useQuery(
      {
        query: searchQuery,
        limit: 20,
        offset: 0,
      },
      {
        enabled: isSearching && searchQuery.length > 0,
      }
    );

  const recipes = isSearching ? searchResults?.recipes : recipeList?.recipes;
  const isLoading = isSearching ? isSearchLoading : isLoadingList;

  const handleSearch = () => {
    if (searchQuery.trim()) {
      setIsSearching(true);
    }
  };

  const handleClearSearch = () => {
    setSearchQuery('');
    setIsSearching(false);
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Recipe Library</CardTitle>
              <CardDescription>
                Reusable environment templates for security testing
              </CardDescription>
            </div>
            <Button onClick={onCreateNew}>
              <Plus className="h-4 w-4 mr-1" />
              Create Recipe
            </Button>
          </div>
        </CardHeader>
      </Card>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex gap-3">
            <div className="flex-1 flex gap-2">
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="Search recipes by name, software, or description..."
                className="flex-1"
              />
              <Button
                onClick={handleSearch}
                disabled={!searchQuery.trim()}
                variant={isSearching ? 'secondary' : 'default'}
              >
                <Search className="h-4 w-4" />
              </Button>
              {isSearching && (
                <Button variant="outline" onClick={handleClearSearch}>
                  Clear
                </Button>
              )}
            </div>

            {!isSearching && (
              <Select value={softwareFilter} onValueChange={setSoftwareFilter}>
                <SelectTrigger className="w-[200px]">
                  <Filter className="h-4 w-4 mr-2" />
                  <SelectValue placeholder="Filter by software" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Software</SelectItem>
                  <SelectItem value="jquery">jQuery</SelectItem>
                  <SelectItem value="react">React</SelectItem>
                  <SelectItem value="angular">Angular</SelectItem>
                  <SelectItem value="vue">Vue.js</SelectItem>
                  <SelectItem value="node">Node.js</SelectItem>
                  <SelectItem value="python">Python</SelectItem>
                  <SelectItem value="java">Java</SelectItem>
                </SelectContent>
              </Select>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-3 w-1/2 mt-2" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-20 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : recipes && recipes.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {recipes.map((recipe) => (
            <RecipeCard
              key={recipe.id}
              recipe={recipe}
              onClick={() => onRecipeClick?.(recipe.id)}
            />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="pt-6 text-center text-muted-foreground">
            {isSearching
              ? 'No recipes found matching your search.'
              : 'No recipes available. Create your first recipe to get started.'}
          </CardContent>
        </Card>
      )}

      {/* Result count */}
      {recipes && recipes.length > 0 && (
        <div className="text-sm text-muted-foreground text-center">
          Showing {recipes.length} recipe{recipes.length !== 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
}
