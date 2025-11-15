# Labs MVP Implementation Plan

## Overview

Implement Labs MVP endpoints with full tenant isolation, authentication requirements, and basic lab lifecycle management. All endpoints require authentication and enforce strict tenant isolation (owner_id == current_user.id).

## Files to Create/Modify

### 1. Lab Service Layer

**`backend/app/services/lab_service.py`** (CREATE)

**Functions to implement:**

1. **`async def create_lab(db: AsyncSession, owner_id: UUID, recipe_id: UUID | None, requested_intent: dict | None) -> Lab`**
   - **Purpose**: Create a new lab for a user with recipe validation
   - **Parameters**:
     - `db`: Database session
     - `owner_id`: UUID of the user creating the lab
     - `recipe_id`: Optional UUID of the recipe to use
     - `requested_intent`: Optional dict with user's raw intent
   - **Logic**:
     - If `recipe_id` is provided:
       - Query Recipe by ID: `await db.get(Recipe, recipe_id)`
       - If recipe not found, raise `HTTPException(404, "Recipe not found")`
       - If recipe exists but `is_active=False`, raise `HTTPException(400, "Recipe is not active")`
     - If `recipe_id` is None, raise `HTTPException(400, "recipe_id is required")` (for MVP, require recipe_id)
     - Create new `Lab` instance:
       - `owner_id=owner_id`
       - `recipe_id=recipe_id`
       - `status=LabStatus.REQUESTED`
       - `requested_intent=requested_intent`
       - `finished_at=None`
   - **Returns**: Created `Lab` instance
   - **Raises**: HTTPException for validation errors

2. **`async def get_user_labs(db: AsyncSession, owner_id: UUID) -> list[Lab]`**
   - **Purpose**: List all labs owned by a user (tenant isolation)
   - **Parameters**:
     - `db`: Database session
     - `owner_id`: UUID of the user
   - **Logic**:
     - Query: `select(Lab).where(Lab.owner_id == owner_id)`
     - Order by `created_at DESC` (newest first)
     - Execute query and return list of Lab instances
   - **Returns**: List of `Lab` instances owned by the user

3. **`async def get_lab_by_id(db: AsyncSession, lab_id: UUID, owner_id: UUID) -> Lab | None`**
   - **Purpose**: Get a single lab by ID with tenant isolation check
   - **Parameters**:
     - `db`: Database session
     - `lab_id`: UUID of the lab to retrieve
     - `owner_id`: UUID of the user (for tenant isolation)
   - **Logic**:
     - Query: `select(Lab).where(Lab.id == lab_id, Lab.owner_id == owner_id)`
     - Execute and return Lab or None
   - **Returns**: `Lab` instance if found and owned by user, `None` otherwise
   - **Security**: Always filters by `owner_id` to enforce tenant isolation

4. **`async def end_lab(db: AsyncSession, lab: Lab) -> Lab`**
   - **Purpose**: Mark a lab as ending/finished
   - **Parameters**:
     - `db`: Database session
     - `lab`: Lab instance to update
   - **Logic**:
     - Check current status
     - If status is `REQUESTED` or `READY`:
       - Set `status = LabStatus.FINISHED`
       - Set `finished_at = datetime.now(timezone.utc)`
     - If status is already `ENDING`, `FINISHED`, or `FAILED`:
       - Optionally raise `HTTPException(400, "Lab is already finished or ending")` or allow idempotent call
     - Commit changes
     - Refresh lab instance
   - **Returns**: Updated `Lab` instance
   - **Note**: For MVP, simple transition: `requested` → `finished` when ended

### 2. Labs Router

**`backend/app/api/routes/labs.py`** (CREATE)

**Router setup:**
- Create `APIRouter` with `prefix="/labs"` and `tags=["labs"]`

**Endpoints to implement:**

1. **POST `/labs`**
   - **Request**: `LabCreate` schema
   - **Response**: `LabResponse` schema (201 Created)
   - **Dependencies**:
     - `current_user: User = Depends(get_current_user)`
     - `db: AsyncSession = Depends(get_db)`
   - **Logic**:
     - Call `lab_service.create_lab()` with:
       - `owner_id=current_user.id`
       - `recipe_id=request.body.recipe_id`
       - `requested_intent=request.body.requested_intent`
     - Commit and refresh lab
     - Return `LabResponse.model_validate(lab)`
   - **Raises**: 400 if recipe validation fails, 404 if recipe not found

2. **GET `/labs`**
   - **Response**: `list[LabResponse]` (200 OK)
   - **Dependencies**:
     - `current_user: User = Depends(get_current_user)`
     - `db: AsyncSession = Depends(get_db)`
   - **Logic**:
     - Call `lab_service.get_user_labs(db, current_user.id)`
     - Convert each Lab to `LabResponse.model_validate(lab)`
     - Return list of `LabResponse`
   - **Security**: Automatically filtered by `owner_id` in service layer

3. **GET `/labs/{lab_id}`**
   - **Path parameter**: `lab_id: UUID`
   - **Response**: `LabResponse` schema (200 OK)
   - **Dependencies**:
     - `current_user: User = Depends(get_current_user)`
     - `db: AsyncSession = Depends(get_db)`
   - **Logic**:
     - Call `lab_service.get_lab_by_id(db, lab_id, current_user.id)`
     - If lab is `None`, raise `HTTPException(404, "Lab not found")`
     - Return `LabResponse.model_validate(lab)`
   - **Security**: Returns 404 (not 403) if lab doesn't exist or isn't owned by user

4. **POST `/labs/{lab_id}/end`**
   - **Path parameter**: `lab_id: UUID`
   - **Response**: `LabResponse` schema (200 OK)
   - **Dependencies**:
     - `current_user: User = Depends(get_current_user)`
     - `db: AsyncSession = Depends(get_db)`
   - **Logic**:
     - Call `lab_service.get_lab_by_id(db, lab_id, current_user.id)`
     - If lab is `None`, raise `HTTPException(404, "Lab not found")`
     - Call `lab_service.end_lab(db, lab)`
     - Return `LabResponse.model_validate(lab)`
   - **Security**: Can only end labs owned by the current user

### 3. Main Application Updates

**`backend/app/main.py`** (MODIFY)

- Add import: `from app.api.routes import auth, health, labs`
- Register router: `app.include_router(labs.router)`
- Place after auth router registration

## Implementation Details

### Tenant Isolation Pattern

**All lab queries must follow this pattern:**

```python
# In service layer
result = await db.execute(
    select(Lab).where(
        Lab.id == lab_id,
        Lab.owner_id == owner_id  # Always include owner_id filter
    )
)
lab = result.scalar_one_or_none()
```

**In routes:**
- Always pass `current_user.id` as `owner_id` parameter
- Never query labs without `owner_id` filter
- Return 404 (not 403) if lab not found or not owned by user

### Status Transitions (MVP)

For MVP, use simple transitions:
- **Creation**: `requested` (default)
- **End action**: `requested` → `finished` (or `ready` → `finished` if already ready)
- Future: `requested` → `provisioning` → `ready` → `ending` → `finished`

### Error Handling

**Recipe validation:**
- Recipe not found → HTTP 404
- Recipe inactive → HTTP 400 with clear message

**Lab access:**
- Lab not found → HTTP 404 (generic message to avoid information leakage)
- Lab not owned by user → HTTP 404 (same message as not found)

**Status transitions:**
- Invalid transition → HTTP 400 with descriptive message
- Lab already finished → HTTP 400 or allow idempotent (prefer idempotent for MVP)

### Database Queries

**Create lab:**
```python
# Validate recipe
recipe = await db.get(Recipe, recipe_id)
if not recipe:
    raise HTTPException(404, "Recipe not found")
if not recipe.is_active:
    raise HTTPException(400, "Recipe is not active")

# Create lab
lab = Lab(
    owner_id=owner_id,
    recipe_id=recipe_id,
    status=LabStatus.REQUESTED,
    requested_intent=requested_intent,
)
db.add(lab)
await db.commit()
await db.refresh(lab)
```

**List labs:**
```python
result = await db.execute(
    select(Lab)
    .where(Lab.owner_id == owner_id)
    .order_by(Lab.created_at.desc())
)
labs = result.scalars().all()
```

**Get single lab:**
```python
result = await db.execute(
    select(Lab).where(
        Lab.id == lab_id,
        Lab.owner_id == owner_id
    )
)
lab = result.scalar_one_or_none()
```

**End lab:**
```python
lab.status = LabStatus.FINISHED
lab.finished_at = datetime.now(timezone.utc)
await db.commit()
await db.refresh(lab)
```

## Security Considerations

1. **Tenant isolation**: Every lab query must include `owner_id == current_user.id` filter
2. **404 vs 403**: Always return 404 (not 403) to avoid leaking lab existence
3. **Authentication**: All endpoints require `get_current_user` dependency
4. **Input validation**: Validate recipe exists and is active before creating lab
5. **Status transitions**: Validate status transitions are allowed

## File Structure Summary

```
backend/
├── app/
│   ├── api/
│   │   └── routes/
│   │       └── labs.py              # CREATE: All lab endpoints
│   ├── services/
│   │   └── lab_service.py           # CREATE: Lab business logic
│   └── main.py                      # MODIFY: Include labs router
```

## Implementation Order

1. Create `app/services/lab_service.py` with all service functions
2. Create `app/api/routes/labs.py` with all four endpoints
3. Update `app/main.py` to include labs router
4. Test endpoints with authentication

## Notes

- All endpoints use async/await patterns consistent with existing codebase
- Database queries use SQLAlchemy 2.x async patterns (`select()`, `db.execute()`, `db.get()`)
- Error responses follow FastAPI conventions (HTTPException)
- Service layer handles business logic; routes are thin wrappers
- Tenant isolation is enforced at the service layer, not just routes
- For MVP, recipe_id is required (no LLM selection yet)

