# Structured LabIntent Implementation Plan

## Overview

Introduce a structured `LabIntent` Pydantic model to replace the generic `dict[str, Any]` for `requested_intent`, while maintaining compatibility with the existing `Lab.requested_intent` JSONB field in the database.

## Files to Modify

### 1. Lab Schemas

**`backend/app/schemas/lab.py`** (MODIFY)

**Changes:**

1. **Create `LabIntent` Pydantic model** (NEW)
   ```python
   class LabIntent(BaseModel):
       """Structured intent schema for lab creation."""
       
       software: str | None = None
       version: str | None = None
       exploit_family: str | None = None
       app_domain: str | None = None
       notes: str | None = None
   ```
   - All fields optional (can be `None`)
   - Uses Pydantic v2 syntax (`str | None`)
   - No `model_config` needed (default behavior is fine)

2. **Update `LabCreate` schema**
   - **Remove**: `requested_intent: dict[str, Any] | None = None`
   - **Add**: `intent: LabIntent | None = None`
   - **Keep**: `recipe_id: UUID | None = None`
   - Result:
     ```python
     class LabCreate(BaseModel):
         recipe_id: UUID | None = None
         intent: LabIntent | None = None
     ```

3. **Keep `LabResponse` unchanged**
   - Still has: `requested_intent: dict[str, Any] | None`
   - This allows backward compatibility with existing DB data
   - The response can contain raw JSONB data from the database

4. **Keep other schemas unchanged**
   - `LabUpdate`, `LabList` remain as-is

### 2. Service Layer Mapping

**`backend/app/services/lab_service.py`** (MODIFY)

**Function to update: `create_lab_for_user()`**

**Current signature:**
```python
async def create_lab_for_user(
    db: AsyncSession,
    owner_id: UUID,
    recipe_id: UUID | None,
    requested_intent: dict | None = None,
) -> Lab:
```

**New signature:**
```python
async def create_lab_for_user(
    db: AsyncSession,
    owner_id: UUID,
    recipe_id: UUID | None,
    intent: LabIntent | None = None,  # Changed from requested_intent: dict | None
) -> Lab:
```

**Mapping logic:**
- Convert `LabIntent` Pydantic model to dict for storage in JSONB
- Use `intent.model_dump(exclude_none=True)` to convert to dict
  - `exclude_none=True` ensures only set fields are stored (cleaner JSONB)
  - Result: `{"software": "Apache", "version": "2.4.18", ...}` or `None` if intent is None
- Store in `Lab.requested_intent` as before:
  ```python
  lab = Lab(
      owner_id=owner_id,
      recipe_id=recipe_id,
      status=LabStatus.REQUESTED,
      requested_intent=intent.model_dump(exclude_none=True) if intent else None,
      finished_at=None,
  )
  ```

### 3. Router Layer

**`backend/app/api/routes/labs.py`** (MODIFY)

**Function to update: `create_lab()` endpoint**

**Current code:**
```python
lab = await create_lab_for_user(
    db=db,
    owner_id=current_user.id,
    recipe_id=request.recipe_id,
    requested_intent=request.requested_intent,
)
```

**New code:**
```python
lab = await create_lab_for_user(
    db=db,
    owner_id=current_user.id,
    recipe_id=request.recipe_id,
    intent=request.intent,  # Changed from requested_intent
)
```

**Import update:**
- Add: `from app.schemas.lab import LabCreate, LabIntent, LabResponse`
- Or keep existing import if `LabIntent` is exported from `lab.py`

## Implementation Details

### Pydantic Model Conversion

**LabIntent → dict (for storage):**
```python
# If intent is provided
if intent:
    intent_dict = intent.model_dump(exclude_none=True)
    # Result: {"software": "Apache", "version": "2.4.18"} (no None values)
else:
    intent_dict = None
```

**dict → LabIntent (for reading, if needed in future):**
```python
# If we need to parse stored JSONB back to LabIntent
if lab.requested_intent:
    intent = LabIntent.model_validate(lab.requested_intent)
else:
    intent = None
```

### Backward Compatibility

**Database storage:**
- `Lab.requested_intent` remains JSONB (no DB migration needed)
- Can store structured data from `LabIntent` or raw dicts from legacy code
- `LabResponse` still returns `dict[str, Any] | None` for flexibility

**API contract:**
- **Input**: Structured `LabIntent` model (type-safe, validated)
- **Storage**: Dict/JSONB (flexible, can evolve)
- **Output**: Dict/JSONB (backward compatible, can contain any structure)

### Type Safety Benefits

**Before:**
```python
requested_intent: dict[str, Any] | None  # No structure, no validation
```

**After:**
```python
intent: LabIntent | None  # Structured, validated fields
```

**Validation:**
- Pydantic automatically validates field types
- Optional fields can be omitted or set to `None`
- Invalid types will raise validation errors at the API boundary

## File Structure Summary

```
backend/
├── app/
│   ├── schemas/
│   │   └── lab.py              # MODIFY: Add LabIntent, update LabCreate
│   ├── services/
│   │   └── lab_service.py      # MODIFY: Update create_lab_for_user signature and mapping
│   └── api/
│       └── routes/
│           └── labs.py         # MODIFY: Update create_lab endpoint
```

## Implementation Order

1. Update `app/schemas/lab.py`:
   - Add `LabIntent` model
   - Update `LabCreate` to use `intent: LabIntent | None`
   - Keep `LabResponse.requested_intent` as `dict[str, Any] | None`

2. Update `app/services/lab_service.py`:
   - Change `create_lab_for_user()` parameter from `requested_intent: dict | None` to `intent: LabIntent | None`
   - Add import: `from app.schemas.lab import LabIntent`
   - Convert `LabIntent` to dict using `intent.model_dump(exclude_none=True)` before storing

3. Update `app/api/routes/labs.py`:
   - Change `create_lab()` to pass `request.intent` instead of `request.requested_intent`
   - Add import for `LabIntent` if needed

## Notes

- **No database migration needed**: `Lab.requested_intent` remains JSONB
- **Backward compatible**: Existing labs with raw dicts in `requested_intent` will still work
- **Type safety**: API now enforces structured intent input
- **Flexible storage**: JSONB can still store any structure if needed in future
- **Clean JSONB**: Using `exclude_none=True` keeps stored JSON clean (no null values)
- **Response format**: `LabResponse` still returns raw dict for maximum flexibility

## Example Usage

**Request body:**
```json
{
  "recipe_id": "123e4567-e89b-12d3-a456-426614174000",
  "intent": {
    "software": "Apache",
    "version": "2.4.18",
    "exploit_family": "RCE",
    "app_domain": "web",
    "notes": "Testing CVE-2021-44228"
  }
}
```

**Stored in DB (requested_intent JSONB):**
```json
{
  "software": "Apache",
  "version": "2.4.18",
  "exploit_family": "RCE",
  "app_domain": "web",
  "notes": "Testing CVE-2021-44228"
}
```

**Response (LabResponse):**
```json
{
  "id": "...",
  "owner_id": "...",
  "recipe_id": "...",
  "status": "requested",
  "requested_intent": {
    "software": "Apache",
    "version": "2.4.18",
    "exploit_family": "RCE",
    "app_domain": "web",
    "notes": "Testing CVE-2021-44228"
  },
  ...
}
```

