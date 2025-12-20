# Admin Allowlist

This document explains how to configure admin access for OctoLab.

## Overview

OctoLab uses an operator-controlled email allowlist for admin authorization. There is no self-service admin escalation - only operators with server access can grant admin privileges.

**Security Properties:**
- Backend-enforced: All admin checks happen server-side. Frontend gating is cosmetic only.
- Deny-by-default: If `OCTOLAB_ADMIN_EMAILS` is not set, all admin endpoints return 403.
- Instant revoke: Admin status is recomputed from the allowlist on each request. Changing the allowlist and restarting the backend immediately revokes access.
- No self-promotion: There are no endpoints for users to make themselves admin.

## Configuration

Set the `OCTOLAB_ADMIN_EMAILS` environment variable to a comma-separated list of admin email addresses:

```bash
# In .env.local
OCTOLAB_ADMIN_EMAILS=admin@example.com,ops@example.com
```

**Parsing rules:**
- Emails are case-insensitive (automatically lowercased)
- Whitespace is trimmed
- Empty entries are ignored

Example: `" Admin@Example.COM,  ops@test.com ,, "` becomes `{"admin@example.com", "ops@test.com"}`

## How to Become Admin (Testing)

1. Add your login email to `OCTOLAB_ADMIN_EMAILS`:
   ```bash
   # In backend/.env.local
   OCTOLAB_ADMIN_EMAILS=your-email@example.com
   ```

2. Restart the backend:
   ```bash
   make dev-down && make dev
   ```

3. Re-login (or refresh your token via `/auth/me`)

4. Verify admin status:
   ```bash
   curl -H "Authorization: Bearer <your-token>" http://localhost:8000/auth/me
   # Response should include: "is_admin": true
   ```

## Admin Endpoints

All endpoints under `/admin/*` require admin authorization:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/maintenance/network-status` | GET | Check Docker network and container counts |
| `/admin/maintenance/cleanup-networks` | POST | Clean up leaked OctoLab networks |

### Network Cleanup

The cleanup endpoint requires explicit confirmation and **refuses if any OctoLab containers are running**:

```bash
# Check status first
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/admin/maintenance/network-status

# Run cleanup (requires confirm=true)
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"confirm": true, "remove_stopped_containers": true}' \
  http://localhost:8000/admin/maintenance/cleanup-networks
```

**Safety guardrails:**
- Returns 403 if user is not in admin allowlist
- Returns 409 if any OctoLab containers are running (stop labs first)
- Requires `confirm: true` in request body or `X-Confirm: true` header
- Only removes networks matching strict lab pattern (`octolab_<uuid>_(lab_net|egress_net)`)
- Never runs `docker network prune` or `docker system prune`

## Implementation Details

### Settings Property

The `Settings` class in `config.py` exposes `admin_emails` as a computed property:

```python
@property
def admin_emails(self) -> set[str]:
    """Parse admin emails from OCTOLAB_ADMIN_EMAILS env var."""
    if not self.admin_emails_raw:
        return set()
    return {
        email.strip().lower()
        for email in self.admin_emails_raw.split(",")
        if email.strip()
    }
```

### require_admin Dependency

The `/admin` router uses a router-wide dependency that enforces the allowlist:

```python
def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Deny-by-default admin check."""
    admin_emails = settings.admin_emails
    if not admin_emails:
        raise HTTPException(403, "Admin access not configured.")
    email = (user.email or "").strip().lower()
    if email not in admin_emails:
        raise HTTPException(403, "Admin access required.")
    return user

router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin)],
)
```

### /auth/me Response

The `/auth/me` endpoint includes `is_admin` computed server-side:

```json
{
  "id": "...",
  "email": "admin@example.com",
  "is_admin": true,
  "created_at": "...",
  "updated_at": "..."
}
```

This is recomputed from the allowlist on each request, not cached in the JWT.

## Troubleshooting

### "Admin access not configured"

The `OCTOLAB_ADMIN_EMAILS` environment variable is empty or not set. Add admin emails and restart the backend.

### "Admin access required"

Your email is not in the allowlist. Check:
1. Is your email exactly in `OCTOLAB_ADMIN_EMAILS`?
2. Did you restart the backend after changing the env var?
3. Did you re-login to get a fresh token?

### Admin status shows false after config change

The backend needs to be restarted for env var changes to take effect. The frontend may also need to refresh the user profile via `/auth/me`.
