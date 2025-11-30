# Profile Page

## **Purpose**
Provides quick, centralized access to personal settings, documents, and subscription management through a clean drop-down interface.

---

## **Layout Overview**

When the user clicks the **Profile icon** (top-right corner of the navigation bar), a **drop-down menu** appears.

The menu is simple, minimal, and uses the brand’s dark theme with high contrast for selected items.

---

### **Menu Structure**

| Item | Description | Notes |
|:------|:-------------|:------|
| **Back to Home** | Returns the user to the main landing page or dashboard overview. | Appears at the **top-left**, separated from the rest of the menu for clarity. |
| **Profile** | Opens the user’s profile page (current section). | **Highlighted** to show it’s active. |
| **Documents** | Opens the user’s created items — labs, uploads, and reports. | May include a small counter showing number of projects. |
| **Subscription** | Displays current plan, payment method, and invoices. | Links to billing settings. |
| **Settings** | Allows the user to update password, notifications, and privacy options. | Opens a modal or sub-page. |
| **Log out** | Signs the user out of the system. | Confirmation dialog required before logout. |

---

### **Design Notes**

- Drop-down background: semi-transparent dark overlay (`rgba(0,0,0,0.9)`).  
- Menu items: white text with soft hover highlight (`#00ffff` or brand teal).  
- Rounded corners, shadow blur for floating feel.  
- Divider lines between sections for visual grouping.  
- Active item (Profile) has a bright accent line on the left edge.  
- Menu automatically closes when user clicks outside it.

---

### **Behavior Flow**

1. User clicks the **Profile icon** in the top-right navigation bar.  
2. The **drop-down menu** slides down smoothly.  
3. Selecting any item either:  
   - Navigates to that section (Profile, Documents, Subscription, Settings), or  
   - Executes an action (Back to Home, Log out).  

---

<center>

[**Back to Home**](#){: .button-secondary }&nbsp;&nbsp;&nbsp;
[**Edit Profile**](#){: .button }

</center>
