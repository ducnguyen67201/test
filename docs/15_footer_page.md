# Footer — CyberOctopus Security

## **Title**
**Global Footer**

Persistent footer displayed when the user scrolls to the bottom of the page.

---

## **Section 1 — Brand Block**

Displays the CyberOctopus brand identity on the left side.

**Elements**
- CyberOctopus **logo** 
- Brand text:
  - **CyberOctopus** — primary brand name (bright color)
  - **SECURITY** — secondary label (white, smaller)

**Behavior**
- Optional: Clicking the brand block navigates to the **Home** page.
- Logo and text are horizontally aligned with consistent spacing.

**Design Notes**
- Background: black
- Brand bright color
- Brand text uses the same heading font as the rest of the app.

---

## **Section 2 — Navigation Links**

Two rows of footer links under the brand block.

**Links**
- **About us**
- **Features**
- **Pricing**
- **Privacy policy**
- **Term of use**
- **Contact us**

**Behavior**
- All links are internal routes.
- Hover state:
  - Text remains white
  - Underline appears in bright color
- Focus state:
  - Clear focus ring for keyboard users.

**Responsive Layout**
- **Desktop / Large screens**
  - Two rows, left-aligned under logo.
- **Tablet / Mobile**
  - Links stacked vertically.
  - Center-aligned with 8–12px spacing between items.

---

## **Section 3 — Social Media Block**

Social icons displayed on the right side of the footer.

**Icons**
- Instagram
- Facebook
- TikTok
- LinkedIn
- Discord
- GitHub

**Handle Text**
- `@cyberoctopusvn` displayed beneath or to the right of the icons.

**Behavior**
- Clicking an icon opens the respective social profile in a new tab:
  - `target="_blank"` and `rel="noopener noreferrer"`
- Hover:
  - Icon scales up slightly (e.g., `transform: scale(1.1)`)
- Active:
  - Quick press animation or reduced scale (e.g., `scale(0.95)`)

**Design Notes**
- Icons are monochrome white to match the footer theme.
- Icon spacing is consistent (e.g., 16–20px between icons).

---

## **Section 4 — Layout & Spacing**

Defines how the footer is positioned and spaced within the page.

**Container**
- Max width: **1280px**
- Centered horizontally in the viewport.
- Horizontal padding: 24px on left and right.

**Vertical Spacing**
- 48px padding above logo/navigation.
- 48px padding below social icons row.
- Optional subtle divider line above the footer:
  - 1px line with low opacity white or grey.

**Alignment**
- **Desktop**
  - Left column: Brand + Navigation.
  - Right column: Social Media Block.
- **Mobile**
  - Order:
    1. Brand block
    2. Navigation links
    3. Social icons + handle
  - All center-aligned.

**Color System**
- Background: `#000000`
- Primary text: `#FFFFFF`
- Accent: `#FFD836`

---

## **Section 5 — Accessibility**

Accessibility rules for the footer.

**Requirements**
- All social icons include `aria-label` attributes  
  (e.g., `"Follow us on Discord"`).
- Minimum font size for links: **16px**.
- Color contrast:
  - White text on black meets WCAG AA.
- Keyboard navigation:
  - All links and icons are focusable.
  - Focus ring is clearly visible.

---

## **Section 6 — Usage Across the App**

Specifies where the footer is rendered.

**Pages**
- Landing page
- Structure page
- Pricing page
- About us/ Contact us pages
- (Optional) Authenticated dashboard pages

**Behavior**
- Footer is part of the **global layout**.
- Does not change between pages (content and layout stay consistent).
