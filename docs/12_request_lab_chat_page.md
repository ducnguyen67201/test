# Request Lab Chat Page

## **Purpose**
Interactive interface for users to request, configure, and launch new CVE testing labs through chat-driven workflow.

---

## **Top Bar / Header**

| Area | Description |
|:-----|:-------------|
| **Brand & Context (Top-Left)** | “**CyberOctopus**” logo text, with subtitle “Request Lab Chat” below. Flush left in header row. |
| **Active Session Indicator (Top-Center / Right)** | Pill badge labeled **Active Session**, rounded with muted background + thin border. |
| **User Area (Top-Right)** | Small 🔔 Notification icon + circular avatar. Vertically aligned with brand. |

---

## **Main Content — Left Column (≈ 70 % width)**

### **Page Title**
**New Lab** — small, left-aligned label under the header.

---

### **Chat Input / Conversation Area**

| Bubble | Details |
|:--------|:---------|
| **Bot Bubble (Left-Aligned)** | Dark rectangle with placeholder *“What do you need?”* + tiny bot avatar. <br>Metadata below: *Bot • Just now*. |
| **User Bubble (Right-Aligned)** | Message text *“TotalCMS CVE-2023-36212 test”*, user avatar on the right, metadata *You • 2 min ago*. |

---

### **Lab Blueprint Card (Primary Focus)**

Large rounded card with subtle shadow and 24 px padding.

| Element | Description |
|:---------|:-------------|
| **Badges (Top-Right)** | • `HIGH RISK` (red pill, #FF4D4F, white text) • `CVE-2023-36212` (gray pill). |
| **Header Label** | **Lab Blueprint** (bold, left-aligned). |
| **Summary Block** | “TotalCMS vulnerability testing environment for CVE-2023-36212. This critical SQL injection flaw allows unauthenticated RCE through the admin panel.” |
| **Metadata Columns** | **Left:** Target System = TotalCMS v2.1.3  /  Lab Components = chips (Vulnerable TotalCMS, Kali Linux, Monitoring Tools). <br> **Right:** Attack Vector = SQL Injection → RCE  /  Estimated Build Time (optional). |

**Chips Style**
- Rounded (999 px) with 6 × 10 px padding.  
- Color codes: teal (Vulnerable App), green (Kali), purple (Monitoring).  
- Hover = small lift + glow.

---

### **Quick-Pick Row**

**Label:** “Recent CVEs – Quick Pick”  
Horizontal scroll list of chips:

`CVE-2023-46604 (ActiveMQ)` | `CVE-2023-34362 (MOVEit)` | `CVE-2023-38831 (WinRAR)`  
→ Clickable chips populate chat or blueprint.

---

### **Action Buttons Row**

| Button | Style / Purpose |
|:--------|:----------------|
| ✏️ **Edit Inputs** | Secondary outline button — opens modal/slide-over to change versions/components. |
| ✅ **Confirm Request** | Bright cyan pill (#00E5FF bg, #002B36 text) — main CTA to launch lab. |

_Sub-note:_ “By confirming you accept the guardrails and auto-cleanup policy.”

---

## **Right Column — Guardrails & Live Controls (Sidebar ≈ 30 %)**

Vertically stacked cards with 16 px spacing.

### **Guardrails Header**
Small title “Guardrails”.

---

### **Active Labs Card**
Displays:
- **Active Labs:** 1  
- **Current Session:** Running 🟢

---

### **Severity Gate Card**
- **Current Request:** HIGH (red label)  
- **Approval Required:** ✓ Approved (green)  
- **Risk Assessment:** Pending (amber)

---

### **TTL Settings Card**
| Setting | Value |
|:----------|:--------|
| Default TTL | 4 h |
| Max Extension | 2 h |
| Auto-cleanup | Toggle [ On ] (green) |

---

### **Resource Limits Card**
Progress bars show live utilization:

| Resource | Usage |
|:-----------|:---------|
| CPU | 15 % ▰▱▱▱ (green) |
| Memory | 32 % ▰▱▱▱ (blue) |

Numeric readouts beside bars.

---

### **Utility Buttons (Bottom)**
- **View Lab History** — secondary.  
- **Configure Limits** — opens limit editor.

---

## **Visual & Interaction Notes**

| Aspect | Details |
|:---------|:---------|
| **Color & Contrast** | Deep charcoal backgrounds, lighter inner cards, primary CTAs in cyan/teal, danger labels in red, accents in amber. |
| **Spacing & Alignment** | Left column stacked with generous padding; sidebar cards aligned top to bottom with even margins. |
| **Interactivity** | Hover on chips/cards adds glow; confirm actions open modals/toasts. |
| **Responsiveness** | Sidebar collapses under main content on mobile; chat + blueprint stack vertically. |
| **Micro Details** | Blueprint card padding = 24 px; border-radius 8 px; Risk badge 999 px radius; CTA pill 10 × 18 px padding; Sidebar card margin-bottom 16 px. |

---

## **Behavior Flow**
1. User opens Request Lab Chat.  
2. System greets with “ What do you need? ” input.  
3. User specifies CVE (e.g. TotalCMS).  
4. Blueprint card renders details + metadata.  
5. User edits inputs or confirms request.  
6. Sidebar updates live usage and guardrail status.

---

## **QA Checklist**
- Active Session badge visible on load.  
- Confirm Request CTA disabled until blueprint ready.  
- Quick-pick chips populate chat correctly.  
- Guardrail cards update in real-time.  
- Mobile layout collapses without overflow.  
- Toast confirmation after lab launch.

---

<center>

[**Edit Inputs**](#){: .button-secondary }&nbsp;&nbsp;&nbsp;
[**Confirm Request**](#){: .button }

</center>
