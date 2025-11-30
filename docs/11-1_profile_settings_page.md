# Profile Settings Page

## **Header**
**Profile Settings**  
_Manage your account settings and preferences._

---

## **Sections**

### 1) Personal Information
_Subtext: “Update your personal details here”_

**Fields**
- **First name** — text input (required)
- **Last name** — text input (required)
- **Email** — read-only text input  
  _Note: “Your email is managed by your authentication provider.” (SSO / federated, not editable)_

**Validation**
- First/Last name: 1–60 chars, no control characters
- Email: must be valid format (server-provided), locked

**States**
- Loading: skeleton inputs
- Error: inline message under field
- Success: non-blocking toast “Profile updated”

---

### 2) Account Information
_Subtext: “View your account details”_

**Display (read-only)**
- **User ID:** `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx` (truncate middle if long, copy-to-clipboard icon)
- **Account Created:** `YYYY-MM-DD`
- **Last Updated:** `YYYY-MM-DD HH:MM TZ`

---

## **Actions**
- **Save Changes** (primary)  
  - Enabled only if any editable field has changed and is valid  
  - On click: PATCH `/me/profile` → optimistic update
- **Cancel** (secondary)  
  - Reverts edits to last saved values

**Keyboard & A11y**
- `Tab` order: First name → Last name → Email → Save → Cancel
- Labels associated via `for`/`id`, aria-live region for success/error toasts
- High contrast focus ring on inputs and buttons

---

## **Layout**
- Two-column on desktop (Personal Information left, Account Information right), single-column on mobile
- Max content width ~720–960px; generous spacing (24px+ between sections)
- Button row pinned at the bottom of the form area on tall screens

---

## **Edge Cases**
- **SSO email mismatch:** show inline info banner:  
  “Email is managed by your identity provider. To change it, update it in your provider’s settings.”
- **Network error on save:** keep user’s edits, show retry CTA
- **Session expired:** prompt re-auth, then retry save automatically

---

## **Copy (placeholders)**
- First name: “Enter your first name”
- Last name: “Enter your last name”
- Email: “you@company.com (managed by SSO)”
- Save Changes / Cancel

---

## **API (example)**
- **GET** `/api/v1/me` → `{ first_name, last_name, email, user_id, created_at, updated_at }`
- **PATCH** `/api/v1/me` body → `{ first_name, last_name }`
- Responses: `200 OK`, `400 validation_error`, `401 unauthorized`, `409 conflict`

---

## **QA Checklist**
- Read-only email can still be selected/copied
- Save disabled when nothing changed
- Copy icon copies full User ID
- Form restores on Cancel
- Works at 320px width; passes keyboard-only navigation
