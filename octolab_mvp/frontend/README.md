# OctoLab Frontend

React + TypeScript app bootstrapped with Vite. Talks to the FastAPI backend running at `http://localhost:8000`.

## Getting Started

```bash
cd frontend
npm install
npm run dev
```

By default the dev server runs on [http://localhost:5173](http://localhost:5173).

### Environment Variables

Set `VITE_API_URL` to point at the backend (defaults to `http://localhost:8000` if not provided). Create a local `.env` with:

```
VITE_API_URL=http://localhost:8000
```

### Available Pages

- `/login` – JWT auth flow
- `/labs` – recipe list + quick “start lab” action and a summary of your labs
- `/labs/:id` – individual lab details with the OctoBox noVNC link

### Auth Flow

- Tokens are stored in `localStorage` (`octolab_token`) and mirrored in the shared Axios client via `setAccessToken`.
- `<AuthProvider>` (see `src/hooks/useAuth.tsx`) loads `/auth/me` on startup to hydrate the current user.
- Protected routes use a `RequireAuth` wrapper so hitting `/labs` or `/labs/:id` without a valid session redirects to `/login`.

### Linting & Build

```bash
npm run build   # production bundle
npm run preview # preview the build locally
```
