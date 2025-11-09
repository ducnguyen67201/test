# API Utilities

Reusable utilities for making authenticated API requests to the Go backend with Clerk JWT tokens.

## Features

- Automatic Clerk JWT token injection
- Type-safe API calls with TypeScript
- React hooks for easy integration
- Error handling
- Loading states
- Support for all HTTP methods (GET, POST, PATCH, DELETE)

## Files

- `client.ts` - Core API client with request functions
- `types.ts` - Re-exports types from centralized `@/types` directory
- `hooks.ts` - React hooks for client components
- `index.ts` - Barrel export for convenience

**Note:** All type definitions are centralized in `apps/web/types/api.ts`

## Usage

### In Client Components

Use the provided hooks for automatic token management and state handling:

```tsx
'use client';

import { useApiGet } from '@/lib/api';
import type { UserProfile } from '@/lib/api';

export function MyComponent() {
  const { get, loading, error } = useApiGet<UserProfile>();

  const handleClick = async () => {
    try {
      const profile = await get('/api/me');
      console.log(profile);
    } catch (err) {
      console.error('Failed to fetch profile:', err);
    }
  };

  return (
    <button onClick={handleClick} disabled={loading}>
      {loading ? 'Loading...' : 'Get Profile'}
    </button>
  );
}
```

### Available Hooks

#### `useApiGet<T>()`
For GET requests:
```tsx
const { get, loading, error } = useApiGet<UserProfile>();
const profile = await get('/api/me');
```

#### `useApiPost<T, B>()`
For POST requests:
```tsx
const { post, loading, error } = useApiPost<UserProfile, CreateUserRequest>();
const profile = await post('/api/users', { name: 'John' });
```

#### `useApiPatch<T, B>()`
For PATCH requests:
```tsx
const { patch, loading, error } = useApiPatch<UserProfile, UpdateProfileRequest>();
const profile = await patch('/api/me', { first_name: 'John' });
```

#### `useApiDelete<T>()`
For DELETE requests:
```tsx
const { delete: del, loading, error } = useApiDelete();
await del('/api/users/123');
```

#### `useApi()`
Generic hook for custom requests:
```tsx
const { request, loading, error } = useApi();
const data = await request('/api/custom', {
  method: 'PUT',
  body: JSON.stringify({ foo: 'bar' })
});
```

### In Server Components

Use `serverApiRequest` for automatic token retrieval:

```tsx
import { serverApiRequest } from '@/lib/api';
import type { UserProfile } from '@/lib/api';

export default async function ProfilePage() {
  const profile = await serverApiRequest<UserProfile>('/api/me');

  return <div>{profile.email}</div>;
}
```

### Manual Token Handling

If you need more control:

```tsx
import { useAuth } from '@clerk/nextjs';
import { clientApiRequest } from '@/lib/api';

const { getToken } = useAuth();
const token = await getToken();
const data = await clientApiRequest('/api/me', token);
```

## Types

Common types are centralized in `apps/web/types/api.ts` and can be imported from:

```typescript
// From centralized types directory (recommended)
import type {
  UserProfile,
  UpdateProfileRequest,
  APIResponse,
  APIErrorResponse
} from '@/types';

// Or from lib/api (re-exported for convenience)
import type {
  UserProfile,
  UpdateProfileRequest
} from '@/lib/api';
```

## Error Handling

The API utilities throw `APIError` instances:

```tsx
import { APIError } from '@/lib/api';

try {
  const data = await get('/api/me');
} catch (err) {
  if (err instanceof APIError) {
    console.log('Status:', err.status);
    console.log('Message:', err.message);
    console.log('Data:', err.data);
  }
}
```

## Configuration

Set the API base URL in your environment variables:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8080
```

Default: `http://localhost:8080`

## Example Component

See `components/TestApiButton.tsx` for a complete example.
