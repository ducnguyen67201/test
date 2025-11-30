Eval Signal Center — Playbooks in Storyboard
============================================

Purpose
-------
Tie the automation playbooks (auto-rerun, rollback, feedback boost, release gate) to the storyboard frames so that each screen communicates not only detection but the next recommended actions.

Frame Overlays
--------------

### Frame 1: Executive Pulse Dashboard
- **Playbook Surface**: Incident spotlight tile includes action chips (e.g., "Queue Targeted Rerun", "Open Datadog").
- **Highlight**: KPI strip shows shield icon when release gate prevented promotion; hover explains latest block.
- **Activity Feed**: Lists automated playbook executions (e.g., "Auto-rerun scheduled by system, 09:15 UTC").
- **Integration Link**: "View Sentry issue" button jumps to associated infra alert.

### Frame 2: Auto-Triggered Experiment Summary
- **Playbook Surface**: Banner with recommended next steps ranked by confidence.
  - Primary CTA: `Queue Focused Rerun` (auto-rerun playbook).
  - Secondary CTA: `Promote to 100%` disabled when guardrail breach pending (release gate).
- **Diff Panel**: "Request Annotation Review" button tying to feedback boost.
- **Notifications Module**: Shows preview of Jira ticket that will be filed if rollback selected.

### Frame 3: Regression Alert Workflow
- **Action Drawer**: Left column lists playbooks with toggles:
  1. `Auto-rerun focused suite` (default on).
  2. `Hold rollout` (release gate).
  3. `Request annotated deep dive`.
  4. `Rollback to Signal-1278`.
- **Context Panel**: For each playbook, displays estimated time to complete and downstream impacts (e.g., "Rollback updates feature flag `support-bot.v2`").
- **Audit Trail**: Records which actions were auto-triggered vs. manually approved.

### Frame 4: Deep Dive Experiment Comparison
- **Failure Gallery**: "Send to Annotation Queue" link triggers feedback boost.
- **Hypothesis Drawer**: Suggests follow-on experiments (e.g., "Try temperature 0.65" button creates new Signal draft).
- **Footer**: `Confirm Metrics Recovered` button available once rerun completes; marks incident resolved.

### Frame 5: Human Feedback Lens
- **Queue Widget**: Shows backlog created by feedback boost playbook; includes SLA countdown.
- **Reviewer Actions**: "Mark Complete" updates incident status.
- **Analytics**: Pie chart displays proportion of incidents resolved via human feedback vs. automated rollback.

### Frame 6: Weekly Workflow Review
- **Outstanding Regression Table**: Columns for "Active Playbooks", "Owner", "Days Open".
- **Summary Cards**: Track how many regressions resolved by each playbook in last week.
- **Shared Links**: Export report includes action log for compliance.

Interaction Flows
-----------------

### 1. Auto-Rerun Flow
1. Regression Alert triggers auto-rerun playbook (Frame 3).
2. Status chip appears in Frame 1 incident tile ("Focused rerun running...").
3. Results post back to Experiment Summary (Frame 2) with link to comparison diff.

### 2. Rollback Flow
1. On Regression Alert, operator clicks `Rollback to Signal-1278`.
2. Modal displays summary, requires confirmation and optional reason.
3. Upon confirmation, system calls deployment API, updates Audit Trail, and posts Slack message.
4. Executive Dashboard updates KPI strip showing rollback executed.

### 3. Feedback Boost Flow
1. From Deep Dive (Frame 4), PM flags top 10 failures for human review.
2. Feedback Lens (Frame 5) auto-creates queue with SLA.
3. Once annotators submit ratings, incident updates with new metrics and confidence score.

### 4. Release Gate Flow
1. When guardrail breached, release gate prevents promotion; Frame 2 CTA disabled with tooltip.
2. CI/CD integration stops deployment and points to Signal ID.
3. Weekly Workflow Review lists blocked releases with owner and required actions to unblock.

Wireframe Callouts
------------------

| Element | Screen | Annotation |
| --- | --- | --- |
| Action Chips | Frame 1 | Quick links to playbooks, placed beneath incident title |
| Action Drawer | Frame 3 | Right-hand panel, each playbook with status pill (Pending, Running, Completed) |
| SLA Timer | Frame 5 | Countdown badge on annotation queue widget |
| Playbook Summary | Frame 6 | Bar chart showing resolution counts by playbook |

Design Notes
------------
- Keep primary CTAs consistent color (e.g., blue) and use warning color (amber) when guardrail blocks action.
- Log every auto-triggered playbook in Activity Feed to maintain trust.
- Provide inline tooltips explaining playbook effects so new users understand automation cost/benefit.
