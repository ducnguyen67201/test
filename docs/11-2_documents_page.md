# Documents Page

## **Title**
**Documents**  
_Access and manage all your documents and workspaces._

---

## **Layout Overview**
A central hub for all user-created content — labs, reports, uploaded files, and collaborative workspaces.  
The page offers a **toggle** between **card view** and **table view** to suit different workflows.

---

### **Header Controls**
- Search bar: filter by title or type.  
- View toggle: Card / Table icon buttons.  
- Sort dropdown: Last Modified / Type / Used / Shared.  
- Create button: **+ Create Your First Lab** (accent button, top-right).

---

### **Card/Table Fields**
| Field | Description |
|:------|:-------------|
| **Title** | e.g. “Apache PrivEsc Lab” |
| **Type** | Lab Setup / Report / File / Workspace |
| **Last Modified** | Date in ISO-friendly format (YYYY-MM-DD) |
| **Used** | Number of credits used to run or store this item |
| **Shared with** | Number of collaborators (hover shows avatars or initials) |
| **Actions (⋮)** | Edit / Share / Delete — with confirmation dialogs |

---

### **Empty State**
When the user has no content yet:

> “You haven’t created any documents yet.  
> Start by [requesting a lab](#request-lab-chat) or [joining a workspace](#pricing).”

Below the message, display a centered accent button:
> **+ Create Your First Lab**

Friendly illustration and soft animation reinforce a welcoming experience.

---

### **Interaction Details**
- Hovering over a card: raises slightly, shadow glow (`rgba(0,255,255,0.15)`).  
- Clicking a title: opens document or lab in new workspace view.  
- Clicking the actions menu (⋮): shows contextual actions (Edit / Share / Delete).  
- Hovering “Shared with” avatars: tooltip with names or initials.  
- Delete confirmation modal: “Are you sure you want to delete this document?” with Cancel / Confirm.

---

### **Navigation Sidebar (Persistent)**
Left-side menu remains consistent with other sections:

