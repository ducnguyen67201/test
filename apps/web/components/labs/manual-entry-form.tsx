'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { CreateLabInputSchema, type CreateLabInput } from '@/lib/schemas/lab-request';
import { AlertCircle } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';

interface ManualEntryFormProps {
  onSubmit: (data: CreateLabInput) => void;
  onCancel: () => void;
  isLoading?: boolean;
}

export function ManualEntryForm({ onSubmit, onCancel, isLoading = false }: ManualEntryFormProps) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<CreateLabInput>({
    resolver: zodResolver(CreateLabInputSchema),
    defaultValues: {
      source: 'manual',
      ttl_hours: 4,
      severity: 'medium',
    },
  });

  const severity = watch('severity');
  const ttlHours = watch('ttl_hours');

  return (
    <Card>
      <CardHeader>
        <CardTitle>Manual Lab Request</CardTitle>
        <CardDescription>
          Create a custom lab request with specific requirements
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* CVE ID (optional) */}
          <div className="space-y-2">
            <Label htmlFor="cve_id">CVE ID (optional)</Label>
            <Input
              id="cve_id"
              placeholder="CVE-2024-1234"
              {...register('cve_id')}
              disabled={isLoading}
            />
            {errors.cve_id && (
              <p className="text-sm text-destructive">{errors.cve_id.message}</p>
            )}
          </div>

          {/* Title */}
          <div className="space-y-2">
            <Label htmlFor="title">
              Title <span className="text-destructive">*</span>
            </Label>
            <Input
              id="title"
              placeholder="Enter vulnerability or test objective"
              {...register('title')}
              disabled={isLoading}
            />
            {errors.title && (
              <p className="text-sm text-destructive">{errors.title.message}</p>
            )}
          </div>

          {/* Severity */}
          <div className="space-y-2">
            <Label htmlFor="severity">
              Severity <span className="text-destructive">*</span>
            </Label>
            <Select
              value={severity}
              onValueChange={(value) => setValue('severity', value as any)}
              disabled={isLoading}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select severity" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="low">Low</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="critical">Critical</SelectItem>
              </SelectContent>
            </Select>
            {errors.severity && (
              <p className="text-sm text-destructive">{errors.severity.message}</p>
            )}
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              placeholder="Describe the vulnerability or test scenario"
              rows={3}
              {...register('description')}
              disabled={isLoading}
            />
            {errors.description && (
              <p className="text-sm text-destructive">{errors.description.message}</p>
            )}
          </div>

          {/* Objective */}
          <div className="space-y-2">
            <Label htmlFor="objective">Objective</Label>
            <Textarea
              id="objective"
              placeholder="What do you want to achieve with this lab?"
              rows={2}
              {...register('objective')}
              disabled={isLoading}
            />
            {errors.objective && (
              <p className="text-sm text-destructive">{errors.objective.message}</p>
            )}
          </div>

          {/* TTL Hours */}
          <div className="space-y-2">
            <Label htmlFor="ttl_hours">Time to Live (hours)</Label>
            <Input
              id="ttl_hours"
              type="number"
              min="1"
              max="8"
              {...register('ttl_hours', { valueAsNumber: true })}
              disabled={isLoading}
            />
            <p className="text-xs text-muted-foreground">
              Default: 4 hours. Maximum: 8 hours (requires admin role for &gt;4h)
            </p>
            {errors.ttl_hours && (
              <p className="text-sm text-destructive">{errors.ttl_hours.message}</p>
            )}
          </div>

          {/* Critical Severity Warning */}
          {severity === 'critical' && (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Critical severity labs require written justification (minimum 50 characters) before confirmation.
              </AlertDescription>
            </Alert>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-4">
            <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading} className="flex-1">
              {isLoading ? 'Creating...' : 'Create Draft'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
