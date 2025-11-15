# Authentication Implementation Plan

## Overview

Implement JWT-based authentication with email/password registration and login, following OctoLab security requirements and existing codebase patterns.

## Files to Create/Modify

### 1. Configuration Updates

**`backend/app/config.py`** (MODIFY)
- Add JWT settings to `Settings` class:
  - `secret_key: str` - JWT signing secret (from env: `JWT_SECRET_KEY`)
  - `algorithm: str = "HS256"` - JWT algorithm (default HS256)
  - `access_token_expire_minutes: int = 30` - Token expiration (from env: `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, default 30)
- Load from environment variables via Pydantic Settings

**`backend/.env.example`** (MODIFY)
- Add example JWT configuration:
  ```
  JWT_SECRET_KEY=your-secret-key-here-change-in-production
  JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
  ```

### 2. Authentication Schemas

**`backend/app/schemas/auth.py`** (CREATE)
- **UserRegister** (request schema):
  - `email: EmailStr`
  - `password: str` (with min_length validation, e.g., min 8 characters)
- **UserLogin** (request schema):
  - `email: EmailStr`
  - `password: str`
- **TokenResponse** (response schema):
  - `access_token: str`
  - `token_type: str = "bearer"`
- **TokenData** (internal schema for JWT payload):
  - `user_id: UUID | None = None`
  - `sub: str | None = None` (subject, typically user ID as string)

### 3. Authentication Service

**`backend/app/services/auth_service.py`** (CREATE)

**Functions to implement:**

1. **`hash_password(password: str) -> str`**
   - Use `passlib.context.CryptContext` with bcrypt
   - Return hashed password string
   - Use `scheme="bcrypt"` and appropriate rounds

2. **`verify_password(plain_password: str, hashed_password: str) -> bool`**
   - Use `passlib.context.CryptContext` to verify
   - Return True if password matches, False otherwise

3. **`create_access_token(data: dict, expires_delta: timedelta | None = None) -> str`**
   - Use `jose.jwt.encode()` to create JWT
   - Include `exp` (expiration), `sub` (subject/user_id), `iat` (issued at)
   - Use secret key and algorithm from settings
   - Return encoded token string

4. **`decode_access_token(token: str) -> TokenData | None`**
   - Use `jose.jwt.decode()` to decode JWT
   - Handle `JWTError` exceptions gracefully
   - Return `TokenData` with user_id, or None on failure
   - Validate expiration and signature

### 4. Authentication Dependencies

**`backend/app/api/deps.py`** (CREATE)

**Functions to implement:**

1. **`get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User`**
   - Extract token from `Authorization: Bearer <token>` header
   - Use `FastAPI.security.OAuth2PasswordBearer` for token extraction
   - Decode token using `auth_service.decode_access_token()`
   - Query database for user by ID: `await db.get(User, token_data.user_id)`
   - If user not found or token invalid, raise `HTTPException(status_code=401, detail="Invalid authentication credentials")`
   - Return `User` model instance
   - **Security note**: Return 401 (not 404) to avoid leaking user existence

2. **`oauth2_scheme: OAuth2PasswordBearer`**
   - Create OAuth2PasswordBearer instance with tokenUrl="/auth/login"
   - Used by `get_current_user` dependency

### 5. Authentication Routes

**`backend/app/api/routes/auth.py`** (CREATE)

**Endpoints to implement:**

1. **POST `/auth/register`**
   - Request: `UserRegister` schema
   - Response: `UserResponse` schema (201 Created)
   - Logic:
     - Check if user with email already exists (query by email)
     - If exists, raise `HTTPException(status_code=400, detail="Email already registered")`
     - Hash password using `auth_service.hash_password()`
     - Create new `User` with email and password_hash
     - Commit to database
     - Return `UserResponse` (exclude password_hash)
   - Dependencies: `db: AsyncSession = Depends(get_db)`

2. **POST `/auth/login`**
   - Request: `UserLogin` schema (via OAuth2PasswordRequestForm or custom form)
   - Response: `TokenResponse` schema (200 OK)
   - Logic:
     - Query user by email: `await db.execute(select(User).where(User.email == email))`
     - If user not found, raise `HTTPException(status_code=401, detail="Incorrect email or password")`
     - Verify password using `auth_service.verify_password()`
     - If password invalid, raise `HTTPException(status_code=401, detail="Incorrect email or password")`
     - Create JWT access token using `auth_service.create_access_token()` with user.id
     - Return `TokenResponse` with access_token and token_type="bearer"
   - Dependencies: `db: AsyncSession = Depends(get_db)`
   - **Security note**: Use generic error message to avoid user enumeration

3. **GET `/auth/me`**
   - Response: `UserResponse` schema (200 OK)
   - Logic:
     - Use `get_current_user` dependency to get authenticated user
     - Return `UserResponse` from current user
   - Dependencies: `current_user: User = Depends(get_current_user)`

**Router setup:**
- Create `APIRouter` with prefix="/auth" and tags=["auth"]
- Register all three endpoints

### 6. Main Application Updates

**`backend/app/main.py`** (MODIFY)
- Import auth router: `from app.api.routes import auth`
- Register router: `app.include_router(auth.router)`

**`backend/app/api/routes/__init__.py`** (MODIFY)
- Export auth router for consistency (optional)

## Implementation Details

### JWT Token Structure

**Payload fields:**
- `sub`: User ID as string (UUID converted to string)
- `exp`: Expiration timestamp (Unix time)
- `iat`: Issued at timestamp (Unix time)

**Token format:**
```
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",  # user.id as string
  "exp": 1234567890,
  "iat": 1234567800
}
```

### Password Hashing

- Use `passlib` with `bcrypt` scheme
- Recommended rounds: 12 (default)
- Store only the hash in database (never plain passwords)

### Error Handling

**Registration:**
- Email already exists → HTTP 400 with clear message
- Invalid email format → Pydantic validation error (422)
- Weak password → Pydantic validation error (422)

**Login:**
- Invalid credentials → HTTP 401 with generic message ("Incorrect email or password")
- User not found → HTTP 401 (same message to avoid enumeration)

**Protected routes:**
- Missing/invalid token → HTTP 401 ("Not authenticated")
- User not found (from token) → HTTP 401 ("Invalid authentication credentials")

### Security Considerations

1. **Password validation**: Enforce minimum length (8+ characters recommended)
2. **JWT secret**: Must be strong, random, and stored in environment variables
3. **Token expiration**: Default 30 minutes, configurable via env
4. **Error messages**: Generic messages to prevent user enumeration
5. **Password hashing**: Use bcrypt with appropriate cost factor
6. **Token storage**: Client-side only (not stored in database for MVP)

### Database Queries

**Registration:**
```python
# Check existing user
result = await db.execute(select(User).where(User.email == email))
existing_user = result.scalar_one_or_none()

# Create new user
new_user = User(email=email, password_hash=hashed_password)
db.add(new_user)
await db.commit()
await db.refresh(new_user)
```

**Login:**
```python
# Find user by email
result = await db.execute(select(User).where(User.email == email))
user = result.scalar_one_or_none()
```

**get_current_user:**
```python
# Get user by ID from token
user = await db.get(User, user_id)
```

## Dependencies Required

Already installed (from terminal history):
- `python-jose[cryptography]` ✓
- `passlib[bcrypt]` ✓

No additional package installations needed.

## Environment Variables

Add to `.env` file:
```
JWT_SECRET_KEY=<strong-random-secret-key>
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
```

## Testing Considerations

**Manual testing endpoints:**
1. POST `/auth/register` - Create new user
2. POST `/auth/login` - Get access token
3. GET `/auth/me` - Verify token works (include `Authorization: Bearer <token>` header)

**Edge cases to handle:**
- Duplicate email registration
- Invalid email format
- Weak passwords
- Non-existent user login
- Wrong password login
- Expired tokens
- Invalid/malformed tokens
- Missing Authorization header

## File Structure Summary

```
backend/
├── app/
│   ├── config.py                    # MODIFY: Add JWT settings
│   ├── api/
│   │   ├── deps.py                  # CREATE: get_current_user dependency
│   │   └── routes/
│   │       ├── __init__.py          # MODIFY: Export auth router (optional)
│   │       └── auth.py              # CREATE: Register, login, me endpoints
│   ├── schemas/
│   │   └── auth.py                  # CREATE: UserRegister, UserLogin, TokenResponse, TokenData
│   └── services/
│       └── auth_service.py         # CREATE: Password hashing, JWT encode/decode
└── .env.example                     # MODIFY: Add JWT config examples
```

## Implementation Order

1. Update `config.py` with JWT settings
2. Create `schemas/auth.py` with request/response schemas
3. Create `services/auth_service.py` with password and JWT utilities
4. Create `api/deps.py` with `get_current_user` dependency
5. Create `api/routes/auth.py` with three endpoints
6. Update `main.py` to include auth router
7. Update `.env.example` with JWT configuration

## Notes

- All endpoints use async/await patterns consistent with existing codebase
- Database queries use SQLAlchemy 2.x async patterns (`select()`, `db.execute()`, `db.get()`)
- Error responses follow FastAPI conventions (HTTPException)
- Security best practices: generic error messages, proper password hashing, JWT expiration
- Token is stateless (no database lookup for token validation, only for user retrieval)
- `get_current_user` will be reusable for all protected routes (labs, recipes, etc.)

