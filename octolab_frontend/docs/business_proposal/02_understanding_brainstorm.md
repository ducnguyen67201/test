North Star

Position it as “continuous eval observability” for AI product teams: every prompt/model change automatically produces a quality + cost + reliability scorecard tied to the source commit.
Target orgs with ≥5 engineers working on production LLM apps where regressions are expensive and leadership needs fast signal.
Workflow Story

Developer A merges a prompt/model change; a pipeline spins up replay evals plus a slice of live traffic.
Dashboard updates the experiment page: headline “Net Eval Score +4.2, latency +6%, cost flat.”
If an eval metric or incident breaching a defined guardrail appears, the system tags the responsible commit(s), posts to Slack with context, and links to rollback options.
PMs see a weekly “workflow” view showing experiments shipped, time-to-eval, approval loops, and human feedback incorporated.
Dashboard Layout

Overview tab: sparkline timeline of “Eval Health,” stacked by accuracy, hallucination, latency; incident call-outs appear inline.
Experiment detail: side-by-side current vs. previous version, diff summary of prompt/model, top failed test cases with repro links.
Workflow analytics: throughput of experiments, median review cycle, % experiments improving key metrics, outstanding regressions.
Feedback lens: annotator rubric scores, disagreement heatmap, total cost/time spent.
Workflow Naming

Borrow observability language: “Eval Signal Center,” “AI Health Timeline,” “Experiment Runbook.”
Individual eval tasks can be “Signals” (e.g., Signal-1276: “Customer Support Bot – empathy prompt tweak”), automatically generated per PR.
Incidents flagged as “Regression Alerts,” linked to owning workflow and assigned owner.
Data Backbone

Core tables: experiments (commit hash, model version, config), eval_runs (dataset, metric bundle, score), incidents, feedback_samples.
Streaming connectors to GitHub/GitLab, inference logs (via SDK or pull from Helicone-style proxy), eval frameworks (OpenAI Evals, Ragas, custom).
Alerting engine with rule packs (accuracy drop >3 pts, latency p95 >1000 ms, hallucination rate spike).
Business Angle

Problem statement: “Teams ship prompt/model changes weekly but lack trustworthy, joined-up visibility into their impact; regressions surface only after customer complaints.”
Solution: “EvalOps platform that auto-correlates code changes, eval outcomes, operational incidents, and human feedback into actionable dashboards and alerts.”
ICP & buyer: Head of AI/ML platform or product engineering lead; budgets similar to Datadog/Sentry line items.
Pricing hypothesis: base platform ($1.5–3k/month) + usage tiered on eval jobs or seats, with enterprise add-ons for HITL module.
Next Steps

Storyboard the "Eval Signal Center" UI-one pager per tab to validate with design partners.
Outline MVP connectors (GitHub, OpenAI logs, CSV eval uploader) and the trigger pipeline for post-commit evals.
Draft customer discovery script to test appetite for regression alerts, feedback analytics, and incident labeling tied to commits.

Storyboard — Eval Signal Center

Frame 1: Executive Pulse Dashboard
- Persona: Head of AI/ML scanning morning status.
- Trigger: Opens Eval Signal Center home.
- View: Hero scorecard with Net Eval Score delta, traffic volume, cost trend, latency p95, and incident count.
- UI elements: Timeline heatmap (accuracy vs hallucination vs latency), regression callouts with commit IDs, filter pill for product surface.
- Insight: Immediate read on whether quality improved overnight and where to drill in.

Frame 2: Auto-Triggered Experiment Summary
- Persona: Staff engineer who merged a prompt PR.
- Trigger: Post-merge pipeline finishes replay eval and production shadow run.
- View: Experiment card titled Signal-1280 with status badge (Pass/Warning), list of metrics vs baseline, traffic sample size.
- UI elements: Diff snippet showing prompt/model changes, run duration, automated comment push to GitHub/Slack.
- Insight: Confirms the change nudged KPIs and whether follow-up action is needed before full rollout.

Frame 3: Regression Alert Workflow
- Persona: On-call AI platform engineer.
- Trigger: Guardrail breach (hallucination rate +5 pts) detected during eval.
- View: Alert banner linking to Incident modal with affected workflows, suspect commits, and impacted datasets.
- UI elements: Suggested rollback button, owner/assignee dropdown, annotation feed for discussion.
- Insight: Fast path to acknowledge, triage, and assign a fix with full traceability.

Frame 4: Deep Dive Experiment Comparison
- Persona: Product PM evaluating trade-offs.
- Trigger: Opens experiment detail from alert or dashboard.
- View: Split screen with Baseline vs Treatment, metric tables, waterfall chart of metric contributions.
- UI elements: Failure case gallery (inputs, model outputs, evaluator notes), toggle for human vs automated evals, download CSV button.
- Insight: Understand why the score moved, which test cases regressed, and whether to accept or revert.

Frame 5: Human Feedback Lens
- Persona: Annotation lead reviewing reviewer throughput.
- Trigger: Selects Feedback tab for the same workflow.
- View: Rubric scores per model version, inter-rater agreement chart, cost/time per labeled example.
- UI elements: Queue status widget, sampling controls, export-to-Jira/Notion actions.
- Insight: Shows human feedback quality and ROI, highlights where additional labeling could unlock gains.

Frame 6: Weekly Workflow Review
- Persona: AI leadership team in weekly sync.
- Trigger: Runs weekly summary mode.
- View: Timeline of Signals shipped, experiment velocity graph, improvement rate, outstanding regression list.
- UI elements: Drill-down links back to Frame 2/4, printable PDF snapshot, share to Slack.
- Insight: Creates shared understanding of progress, bottlenecks, and upcoming priorities.

Cross-Screen Glue
- Universal filters to pivot by product surface, dataset, team, or model version.
- Breadcrumb showing Workflow > Signal > Incident/Feedback to keep context.
- Activity feed capturing commits, eval runs, annotations, SLAs in chronological order.
- Contextual tooltips educating new users on metric definitions and guardrail logic.

Differentiation vs. Regression Test Generators (e.g., Reptile-style tools)

- Scope of signal: regression generators focus on functional correctness of endpoints; Eval Signal Center layers quality, cost, hallucination, and human feedback metrics specific to LLM workflows.
- Attribution engine: we correlate each change to prompt/model commits, datasets, and annotator actions so teams see why a regression happened—not just that a test failed.
- Mixed evaluation modes: blend automated eval suites, curated benchmark runs, production shadow traffic, and human rubric scoring in one timeline.
- Workflow visibility: show experiment velocity, approval loops, and unresolved regressions; standard generators do not model the human & process layer.
- Guardrail intelligence: AI-specific thresholds (hallucination rate, rubric scores, drift) trigger alerts with suggested rollback/mitigation guidance.
- Data ingestion breadth: unify Git metadata, inference logs, eval outputs, and feedback annotations; regression tools only read code and runtime to synthesize tests.
