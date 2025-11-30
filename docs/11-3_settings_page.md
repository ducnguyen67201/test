# Settings Page

## **Title**
**Settings**  
_Customize your preferences, security, and privacy._

---

## **Section 1: Notifications**

### **Subheader**
**Notifications**

_Subtext: “Control how and when you receive updates.”_

---

### **Table Layout**
| 🔧 Setting | 📘 Description | 💡 Toggle |
|:-----------|:---------------|:----------|
| 🔔 **Email Alerts** | Notifies when a lab, document, or report is shared. | [ On / Off ] |
| 🧠 **AI Updates** | Sends product insights and automation summaries. | [ On / Off ] |
| 🧾 **Billing Reminders** | Alerts the user about payment or renewal schedules. | [ On / Off ] |

**Design Notes**
- Use simple horizontal dividers between rows.  
- Toggling [ On / Off ] animates via a soft glow (teal accent).  
- Columns resize fluidly for tablet and mobile screens.

---

## **Section 2: Security**

### **Subheader**
**Security & Password**

_Subtext: “Keep your account safe.”_

**Form Fields**
- **Current Password**
- **New Password**
- **Confirm New Password**

Primary button: **Update Password**  

**Note:**  
> “Use at least 8 characters, one number, and one symbol.”

Optional additional item:
- **Two-Factor Authentication:** [Enabled / Disabled]

---

### **Actions (Bottom Row)**
- **Save All Changes** — Primary button  
- **Reset to Defaults** — Secondary outlined button  

_On successful save, show toast:_  
> “Settings updated successfully.”

---

## **Layout**
- Two-column on desktop (Notifications left, Security right).  
- Single column on mobile with sections stacked vertically.  
- Padding between sections: 32–40px.  
- Accent color for buttons: brand teal (#00ffff) with dark hover gradient.

---

## **Sidebar Navigation (Persistent)**
