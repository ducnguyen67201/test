# Authentication Troubleshooting Guide

## Issue: Getting 401 Unauthorized

### What I've Added:

1. **Frontend Debug Logging** (TestApiButton.tsx)
   - Now shows token retrieval status
   - Logs token length and first 50 characters to console
   - Displays debug info in the UI

2. **Backend Debug Logging** (clerk.go middleware)
   - Logs when Authorization header is missing
   - Shows token length and preview
   - Displays detailed verification error messages
   - Confirms successful authentication

### How to Debug:

#### Step 1: Check Frontend Token
1. Open browser DevTools (F12)
2. Go to Console tab
3. Click "Get My Profile" button
4. Look for:
   ```
   🔑 Token retrieved: Yes (length: XXX)
   🔑 Token (first 50 chars): eyJhb...
   ```

**If you DON'T see a token:**
- User is not signed in properly with Clerk
- Clerk configuration issue in frontend

#### Step 2: Check Backend Logs
Look at your API server console output:

**Scenario A: No Authorization header**
```
❌ [AUTH] No Authorization header found
```
**Problem:** Frontend is not sending the token
**Solution:** Check that the API client is attaching the token

**Scenario B: Token sent but verification failed**
```
🔑 [AUTH] Authorization header present (length: XXX)
🔑 [AUTH] Token preview: Bearer eyJhb...
❌ [AUTH] Token verification failed: <error details>
```
**Problem:** Token format is wrong OR Clerk secret key is incorrect
**Solutions:**
1. Verify `CLERK_SECRET_KEY` in `.env.local` matches your Clerk dashboard
2. Check that the token starts with `Bearer ` (should be auto-handled)
3. Ensure your Clerk secret key is for the same environment (test/prod)

**Scenario C: Success**
```
🔑 [AUTH] Authorization header present (length: XXX)
🔑 [AUTH] Token preview: Bearer eyJhb...
✅ [AUTH] Token verified successfully for user: user_xxxxx
```
**Status:** Authentication working! 🎉

### Common Issues:

#### 1. Wrong Clerk Secret Key
**Symptoms:** Token verification always fails
**Solution:**
- Go to Clerk Dashboard → API Keys
- Copy the **Secret Key** (starts with `sk_test_` or `sk_live_`)
- Update `CLERK_SECRET_KEY` in `.env.local`
- Restart the API server

#### 2. Token Not Being Sent
**Symptoms:** Backend shows "No Authorization header found"
**Solution:**
- Check browser Network tab → Request Headers
- Should see: `Authorization: Bearer eyJhbG...`
- Verify user is signed in (check Clerk UI state)

#### 3. CORS Issues
**Symptoms:** Request fails before reaching backend
**Solution:**
- Check `API_CORS_ORIGINS` in `.env.local` includes `http://localhost:3000`
- Verify CORS middleware is configured correctly

#### 4. Wrong API URL
**Symptoms:** Network error, can't connect
**Solution:**
- Frontend `.env.local`: `NEXT_PUBLIC_API_URL=http://localhost:8080`
- Verify API server is running on port 8080

### Verification Checklist:

- [ ] API server is running (`go run cmd/server/main.go`)
- [ ] Frontend is running (`npm run dev`)
- [ ] User is signed in with Clerk
- [ ] `.env.local` has correct `CLERK_SECRET_KEY`
- [ ] `.env.local` has correct `NEXT_PUBLIC_API_URL`
- [ ] `.env.local` has correct `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
- [ ] Both frontend and backend are reading from `.env.local` in the repo root

### Testing Flow:

1. **Start backend:**
   ```bash
   cd apps/api
   go run cmd/server/main.go
   ```

2. **Start frontend:**
   ```bash
   cd apps/web
   npm run dev
   ```

3. **Sign in** through Clerk

4. **Click "Get My Profile"** button

5. **Check both consoles:**
   - Browser console (frontend logs)
   - Terminal console (backend logs)

### Expected Behavior:

**Browser Console:**
```
🔑 Token retrieved: Yes (length: 450)
🔑 Token (first 50 chars): eyJhbGciOiJSUzI1NiIsImtpZCI6Imluc18yY...
```

**API Server Console:**
```
🔑 [AUTH] Authorization header present (length: 457)
🔑 [AUTH] Token preview: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imluc18yY...
✅ [AUTH] Token verified successfully for user: user_2abc123def
[2025-11-08 23:30:00.123] INFO logging.go:30 - Request processed | method=GET path=/api/me status=200 latency=15ms ip=::1
```

### Need More Help?

1. Share both frontend and backend console outputs
2. Verify your `.env.local` configuration (without revealing actual secrets)
3. Check Clerk Dashboard for any API key issues
