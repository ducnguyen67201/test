'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Package,
  Server,
  Shield,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Edit2,
  Save,
  X,
  Loader2,
  Calendar,
  User,
  Link as LinkIcon,
  Play,
  PlayCircle,
} from 'lucide-react';
import { trpc } from '@/lib/trpc/client';
import type { Recipe, RecipeValidationResult } from '@/lib/schemas/recipe';

interface RecipeDetailProps {
  recipeId: string;
  onClose?: () => void;
}

export function RecipeDetail({ recipeId, onClose }: RecipeDetailProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedName, setEditedName] = useState('');
  const [editedDescription, setEditedDescription] = useState('');

  // Get recipe details
  const { data: recipe, refetch, isLoading } = trpc.recipe.getById.useQuery({ recipeId });

  // Validate recipe
  const { data: validation, refetch: refetchValidation } = trpc.recipe.validate.useQuery(
    { recipeId },
    { enabled: !!recipe }
  );

  // Update mutation
  const update = trpc.recipe.update.useMutation({
    onSuccess: () => {
      refetch();
      setIsEditing(false);
    },
  });

  // Activate/Deactivate mutations
  const activate = trpc.recipe.activate.useMutation({
    onSuccess: () => refetch(),
  });

  const deactivate = trpc.recipe.deactivate.useMutation({
    onSuccess: () => refetch(),
  });

  const handleStartEdit = () => {
    if (recipe) {
      setEditedName(recipe.name);
      setEditedDescription(recipe.description || '');
      setIsEditing(true);
    }
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditedName('');
    setEditedDescription('');
  };

  const handleSaveEdit = () => {
    update.mutate({
      recipeId,
      name: editedName,
      description: editedDescription || undefined,
    });
  };

  const handleToggleActive = () => {
    if (recipe?.is_active) {
      deactivate.mutate({ recipeId });
    } else {
      activate.mutate({ recipeId });
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin" />
            Loading Recipe...
          </CardTitle>
        </CardHeader>
      </Card>
    );
  }

  if (!recipe) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recipe Not Found</CardTitle>
          <CardDescription>The requested recipe could not be found.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between">
            <div className="flex-1">
              {isEditing ? (
                <div className="space-y-3">
                  <Input
                    value={editedName}
                    onChange={(e) => setEditedName(e.target.value)}
                    placeholder="Recipe name"
                    className="text-lg font-semibold"
                  />
                  <Textarea
                    value={editedDescription}
                    onChange={(e) => setEditedDescription(e.target.value)}
                    placeholder="Recipe description"
                    rows={2}
                  />
                </div>
              ) : (
                <>
                  <CardTitle className="text-2xl">{recipe.name}</CardTitle>
                  <CardDescription className="mt-2">
                    {recipe.description || 'No description provided'}
                  </CardDescription>
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={recipe.is_active ? 'default' : 'secondary'}>
                {recipe.is_active ? 'Active' : 'Inactive'}
              </Badge>
              {isEditing ? (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleCancelEdit}
                    disabled={update.isPending}
                  >
                    <X className="h-4 w-4 mr-1" />
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleSaveEdit}
                    disabled={!editedName.trim() || update.isPending}
                  >
                    {update.isPending ? (
                      <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4 mr-1" />
                    )}
                    Save
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="outline" onClick={handleStartEdit}>
                  <Edit2 className="h-4 w-4 mr-1" />
                  Edit
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Validation Status */}
      {validation && (
        <Alert variant={validation.is_valid ? 'default' : 'destructive'}>
          {validation.is_valid ? (
            <CheckCircle2 className="h-4 w-4" />
          ) : (
            <XCircle className="h-4 w-4" />
          )}
          <AlertDescription>
            {validation.is_valid ? (
              'Recipe is valid and ready to use'
            ) : (
              <>
                <strong>Validation Failed:</strong>
                <ul className="mt-2 list-disc list-inside">
                  {validation.errors.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
                {validation.warnings && validation.warnings.length > 0 && (
                  <>
                    <strong className="mt-2 block">Warnings:</strong>
                    <ul className="mt-1 list-disc list-inside">
                      {validation.warnings.map((warning, index) => (
                        <li key={index}>{warning}</li>
                      ))}
                    </ul>
                  </>
                )}
              </>
            )}
          </AlertDescription>
        </Alert>
      )}

      {/* Software & OS */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Environment Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium flex items-center gap-1">
                <Server className="h-4 w-4" />
                Software
              </label>
              <p className="text-sm text-muted-foreground mt-1">{recipe.software}</p>
            </div>
            <div>
              <label className="text-sm font-medium">Operating System</label>
              <Badge variant="outline" className="mt-1">
                {recipe.os}
              </Badge>
            </div>
          </div>

          {recipe.version_constraint && (
            <div>
              <label className="text-sm font-medium">Version Constraint</label>
              <p className="text-sm text-muted-foreground mt-1">{recipe.version_constraint}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Packages */}
      {recipe.packages && recipe.packages.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Package className="h-5 w-5" />
              Packages ({recipe.packages.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {recipe.packages.map((pkg, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between p-3 border rounded-md"
                >
                  <div className="flex items-center gap-2">
                    <Package className="h-4 w-4 text-muted-foreground" />
                    <span className="font-medium">{pkg.name}</span>
                  </div>
                  {pkg.version && (
                    <Badge variant="secondary" className="text-xs">
                      v{pkg.version}
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* CVE Information */}
      {recipe.cve_data && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              CVE Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between p-4 bg-muted rounded-lg">
              <div>
                <h4 className="font-semibold text-lg">{recipe.cve_data.id}</h4>
                {recipe.cve_data.description && (
                  <p className="text-sm text-muted-foreground mt-1">
                    {recipe.cve_data.description}
                  </p>
                )}
              </div>
              {recipe.cve_data.cvss_score && (
                <Badge variant="destructive" className="text-lg px-3 py-1">
                  CVSS: {recipe.cve_data.cvss_score.toFixed(1)}
                </Badge>
              )}
            </div>

            {recipe.cve_data.published_date && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Calendar className="h-4 w-4" />
                Published: {new Date(recipe.cve_data.published_date).toLocaleDateString()}
              </div>
            )}

            {recipe.cve_data.references && recipe.cve_data.references.length > 0 && (
              <div>
                <label className="text-sm font-medium mb-2 block">References</label>
                <div className="space-y-1">
                  {recipe.cve_data.references.map((ref, index) => (
                    <a
                      key={index}
                      href={ref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-sm text-primary hover:underline"
                    >
                      <LinkIcon className="h-3 w-3" />
                      {ref}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Compliance Controls */}
      {recipe.compliance_controls && recipe.compliance_controls.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Shield className="h-5 w-5" />
              Compliance Controls
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {recipe.compliance_controls.map((control, index) => (
                <Badge key={index} variant="outline" className="text-sm">
                  {control.toUpperCase()}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Network Requirements */}
      {recipe.network_requirements && recipe.network_requirements.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Network Requirements</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {recipe.network_requirements.map((req, index) => (
                <div key={index} className="p-3 border rounded-md">
                  <p className="text-sm">{req}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Validation Checks */}
      {recipe.validation_checks && recipe.validation_checks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5" />
              Validation Checks
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {recipe.validation_checks.map((check, index) => (
                <div key={index} className="flex items-start gap-2 p-3 border rounded-md">
                  <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5" />
                  <p className="text-sm">{check}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Source URLs */}
      {recipe.source_urls && recipe.source_urls.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <LinkIcon className="h-5 w-5" />
              Source URLs
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {recipe.source_urls.map((url, index) => (
                <a
                  key={index}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-sm text-primary hover:underline"
                >
                  <LinkIcon className="h-3 w-3" />
                  {url}
                </a>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Metadata */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Metadata</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <label className="font-medium flex items-center gap-1">
                <Calendar className="h-4 w-4" />
                Created
              </label>
              <p className="text-muted-foreground mt-1">
                {new Date(recipe.created_at).toLocaleString()}
              </p>
            </div>
            <div>
              <label className="font-medium flex items-center gap-1">
                <User className="h-4 w-4" />
                Created By
              </label>
              <p className="text-muted-foreground mt-1">{recipe.created_by}</p>
            </div>
          </div>

          {recipe.updated_at && (
            <div className="text-sm">
              <label className="font-medium">Last Updated</label>
              <p className="text-muted-foreground mt-1">
                {new Date(recipe.updated_at).toLocaleString()}
              </p>
            </div>
          )}

          {recipe.intent_id && (
            <div className="text-sm">
              <label className="font-medium">Created from Intent</label>
              <p className="text-muted-foreground mt-1 font-mono text-xs">
                {recipe.intent_id}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Actions */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex justify-between">
            <Button
              variant="outline"
              onClick={handleToggleActive}
              disabled={activate.isPending || deactivate.isPending}
            >
              {activate.isPending || deactivate.isPending ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              ) : recipe.is_active ? (
                <XCircle className="h-4 w-4 mr-1" />
              ) : (
                <PlayCircle className="h-4 w-4 mr-1" />
              )}
              {recipe.is_active ? 'Deactivate' : 'Activate'}
            </Button>

            {onClose && (
              <Button variant="outline" onClick={onClose}>
                Close
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
