# Change Plan Page

## **Title**
**Change Your Subscription Plan**

---

## **Current Plan Summary (Top Box)**

Small summary card that displays:

- **Current Plan:** e.g., Pro (Monthly)
- **Price:** 250 000 VND / month
- **Renews On:** December 1, 2025

Styling:
- Soft border, dark background
- Slight shadow and rounded corners
- Appears centered or left-aligned depending on layout

---

## **Available Plans (Radio Cards)**

Users must select **one** plan. Cards behave like radio buttons.

### **Plan Cards**
Each card includes:

- Plan name (Free, Premium, Scale)
- Price in **bold**
- Mini feature list
- A **checkmark** (✓) appears when selected
- Card highlights with teal glow on hover
- Selected state has a thick accented border

**Plan Examples**

#### **1. Free**
- **0 VND / month**
- Basic labs  
- Limited storage  
- Community support  
Ideal for learners or quick testing.

#### **2. Premium**
- **250 000 VND / month**  
- Full access to all labs  
- AI-generated templates  
- Faster build queue

#### **3. Scale**
- **950 000 VND / month**  
- Shared labs for teams  
- Priority support  
- Higher resource limits

(Plan IDs + backend mapping handled via `/api/v1/plans`.)

---

## **Billing Frequency Toggle**

Small switch above or beside the plan cards:

