# Subscription Page

## **Header**
**Subscription**  
_Manage your plan, payment methods, and invoices._

---

## **Section 1 — Current Plan Overview**

### **Summary Table**

| **Field** | **Value** |
|:-----------|:-----------|
| **Current Plan** | Pro (Monthly) |
| **Status** | Active |
| **Next Billing Date** | December 1, 2025 |
| **Price** | 250 000 VND / month |
| **Payment Method** | Visa •••• 3014 |
| **Last Invoice** | [Download PDF](https://api.cyberoctopus.vn/invoices/12345.pdf) |

**Field Types**
- *Current Plan:* string — `"Free" | "Pro (Monthly)" | "Pro (Annual)" | "Enterprise"`  
- *Status:* enum — `"Active" | "Inactive" | "Cancelled" | "Expired" | "Pending"`  
- *Next Billing Date:* date (nullable)  
- *Price:* formatted currency string  
- *Payment Method:* masked string  
- *Last Invoice:* hyperlink (optional)

---

### **Actions**
- **Change Plan** — primary button  
- **Update Payment Method** — secondary button  

_On click:_ opens modal or navigates to a sub-page for plan or payment management.

---

## **Section 2 — Billing & Payment**

### **Sub-section: Payment Methods**
Default card displayed with mask (e.g. `Visa •••• 3014`).

**Buttons**
- Add New Card  
- Remove Card  

Backend: `POST / api/v1/payment-methods` and `DELETE / api/v1/payment-methods/{id}`

---

### **Sub-section: Billing Information**
Editable form fields:

| Field | Example / Notes |
|:-------|:----------------|
| **Company Name** | “CyberOctopus VN LLC” |
| **Tax ID** | “VN-0123456789” |
| **Billing Address** | “12 Phan Dang Luu St., HCMC” |
| **Country** | Dropdown / Autocomplete |

Button: **Save Changes**

_On save:_ PATCH `/api/v1/billing-info`

---

### **Sub-section: Invoices**

| **Date** | **Amount** | **Status** | **Invoice** |
|:----------|:------------|:------------|:-------------|
| Nov 1 2025 | 250 000 VND | Paid | [Download](https://api.cyberoctopus.vn/invoices/INV-2025-1101.pdf) |
| Oct 1 2025 | 250 000 VND | Paid | [Download](https://api.)
