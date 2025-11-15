'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Package,
  Server,
  Shield,
  MoreVertical,
  Power,
  PowerOff,
  Trash2,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import type { Recipe } from '@/lib/schemas/recipe';
import { trpc } from '@/lib/trpc/client';

interface RecipeCardProps {
  recipe: Recipe;
  onClick?: () => void;
}

export function RecipeCard({ recipe, onClick }: RecipeCardProps) {
  const utils = trpc.useUtils();

  // Mutations
  const activate = trpc.recipe.activate.useMutation({
    onSuccess: () => utils.recipe.list.invalidate(),
  });

  const deactivate = trpc.recipe.deactivate.useMutation({
    onSuccess: () => utils.recipe.list.invalidate(),
  });

  const deleteRecipe = trpc.recipe.delete.useMutation({
    onSuccess: () => utils.recipe.list.invalidate(),
  });

  const handleActivate = (e: React.MouseEvent) => {
    e.stopPropagation();
    activate.mutate({ recipeId: recipe.id });
  };

  const handleDeactivate = (e: React.MouseEvent) => {
    e.stopPropagation();
    deactivate.mutate({ recipeId: recipe.id });
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm('Are you sure you want to delete this recipe?')) {
      deleteRecipe.mutate({ recipeId: recipe.id });
    }
  };

  return (
    <Card className="cursor-pointer hover:shadow-md transition-shadow" onClick={onClick}>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <CardTitle className="text-lg line-clamp-1">{recipe.name}</CardTitle>
            <CardDescription className="line-clamp-2 mt-1">
              {recipe.description || 'No description provided'}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={recipe.is_active ? 'default' : 'secondary'}>
              {recipe.is_active ? 'Active' : 'Inactive'}
            </Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {recipe.is_active ? (
                  <DropdownMenuItem onClick={handleDeactivate}>
                    <PowerOff className="h-4 w-4 mr-2" />
                    Deactivate
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onClick={handleActivate}>
                    <Power className="h-4 w-4 mr-2" />
                    Activate
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleDelete} className="text-destructive">
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Software & OS */}
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-1">
            <Server className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium">{recipe.software}</span>
          </div>
          <Badge variant="outline" className="text-xs">
            {recipe.os}
          </Badge>
        </div>

        {/* Packages */}
        {recipe.packages && recipe.packages.length > 0 && (
          <div className="flex items-center gap-2">
            <Package className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">
              {recipe.packages.length} package{recipe.packages.length !== 1 ? 's' : ''}
            </span>
            <div className="flex flex-wrap gap-1">
              {recipe.packages.slice(0, 3).map((pkg, index) => (
                <Badge key={index} variant="secondary" className="text-xs">
                  {pkg.name}
                </Badge>
              ))}
              {recipe.packages.length > 3 && (
                <Badge variant="secondary" className="text-xs">
                  +{recipe.packages.length - 3} more
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* CVE Badge */}
        {recipe.cve_data && (
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-destructive" />
            <Badge variant="destructive" className="text-xs">
              {recipe.cve_data.id}
              {recipe.cve_data.cvss_score && ` • ${recipe.cve_data.cvss_score.toFixed(1)}`}
            </Badge>
          </div>
        )}

        {/* Compliance Controls */}
        {recipe.compliance_controls && recipe.compliance_controls.length > 0 && (
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-muted-foreground" />
            <div className="flex flex-wrap gap-1">
              {recipe.compliance_controls.map((control, index) => (
                <Badge key={index} variant="outline" className="text-xs">
                  {control.toUpperCase()}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Created Info */}
        <div className="text-xs text-muted-foreground pt-2 border-t">
          Created {new Date(recipe.created_at).toLocaleDateString()}
        </div>
      </CardContent>
    </Card>
  );
}
