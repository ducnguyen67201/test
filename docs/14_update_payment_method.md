# Update Payment Method Page

## **Title**
**Update Payment Method**

---

## **Section 1 — Current Payment Info**

Shows the user’s existing default payment method in a small summary card.

**Example Display**
- **Visa •••• 3014** — expires **06/28**
- Masked number, brand icon, expiry date

**Action**
- **Remove** button (red outline)
  - Opens a confirmation modal:  
    “Are you sure you want to remove this card? You may lose access if no valid payment method remains.”

**Design Notes**
- Soft bordered box, dark panel  
- Masking always enforced (`•••• 3014`)  
- Icon automatically chosen based on BIN  

---

## **Section 2 — Add New Card Form**

A secure form to add new or replacement cards.

**Fields**
- **Cardholder Name** — text input  
- **Card Number** — numeric input with auto-group spacing  
- **Expiration (MM/YY)** — two-part month/year input  
- **CVV** — 3–4 digit numeric field  
- **Set as default payment method** — checkbox

**Real-Time Validation**
- Inline errors under fields  
- Green ✓ success indicator on valid fields  
- Red error message on invalid or incomplete entries  
- Card type auto-detected (Visa, Mastercard, Amex, JCB, etc.)

**Security UI**
- Small lock icon next to the form header  
- Line of text:  
  > “Secured by **Stripe / PayPal / VNPay**”  
- CVV explanation tooltip for accessibility

---

## **Section 3 — Actions**

| Button | Purpose |
|:--------|:---------|
| **Save Payment Method** (primary) | Validates and提交 card info to billing provider |
| **Cancel** (secondary) | Returns to Subscription page without saving |

**Success State**
- Toast:  
  > **“Your payment method has been updated.”**
- Subscription page refreshes with new default card

**Remove Card Behavior**
- If “Remove” is clicked:  
  - Show modal (Cancel / Confirm)  
  - On Confirm → DELETE request  
  - If no valid payment method remains → show inline warning:  
    “A valid payment method is required to maintain your subscription.”

---

## **API Behavior**

- **GET /api/v1/payment-methods**
  Returns default card + metadata.

- **POST /api/v1/payment-methods**
  Body:
  ```json
  {
    "cardholder_name": "John Doe",
    "number": "4242424242424242",
    "exp_month": 6,
    "exp_year": 2028,
    "cvv": "123",
    "default": true
  }
