Eval Signal Center — Automation API Contracts
=============================================

Overview
--------
These API contracts power automation playbooks (auto-rerun, rollback, feedback boost, release gates) invoked by the UI and integrations. All endpoints live under `/v1` and require authentication via bearer token or signed service token.

Authentication & Headers
------------------------
- `Authorization: Bearer <token>` (JWT signed by Eval Signal Center).
- `X-Request-Id` optional idempotency key; recommended for operations creating jobs (rerun, rollback).
- `Content-Type: application/json`.

Common Response Envelope
------------------------
```json
{
  "status": "success",
  "data": { ... },
  "trace_id": "trc_abc123"
}
```
Errors return HTTP 4xx/5xx with:
```json
{
  "status": "error",
  "error": {
    "code": "invalid_state",
    "message": "Signal is already rolled back",
    "details": {}
  },
  "trace_id": "trc_abc123"
}
```

Endpoints
---------

### 1. Trigger Focused Rerun
- **Method/Path**: `POST /v1/signals/{signal_id}/reruns`
- **Description**: Queue a rerun using specified dataset scope and parameters.
- **Request Body**:
```json
{
  "datasets": ["escalations_eval_set", "billing_queries"],
  "sample_size": 50,
  "run_type": "focused",          // enum: focused, full, shadow
  "notes": "Validate empathy prompt regression",
  "priority": "high"
}
```
- **Response (202)**:
```json
{
  "status": "success",
  "data": {
    "rerun_id": "rr_57c9",
    "signal_id": "Signal-1280",
    "queued_at": "2024-06-05T09:18:02Z",
    "estimated_start": "2024-06-05T09:20:00Z",
    "status": "queued"
  },
  "trace_id": "trc_e52"
}
```
- **Errors**:
  - `409` `invalid_state` when signal already has active rerun.
  - `404` `not_found` if signal_id unknown.

### 2. Execute Rollback
- **Method/Path**: `POST /v1/signals/{signal_id}/rollback`
- **Description**: Revert workflow to prior signal or model version; invokes deployment integration.
- **Request Body**:
```json
{
  "target_signal_id": "Signal-1278",
  "reason": "Hallucination guardrail breach",
  "dry_run": false,
  "metadata": {
    "approved_by": "alice.chen",
    "ticket": "AI-482"
  }
}
```
- **Response (200)**:
```json
{
  "status": "success",
  "data": {
    "signal_id": "Signal-1280",
    "rollback_to": "Signal-1278",
    "status": "in_progress",
    "deployment_job_id": "deploy_993a",
    "started_at": "2024-06-05T09:22:10Z"
  },
  "trace_id": "trc_e89"
}
```
- **Errors**:
  - `423` `guardrail_blocked` when release gate requires human approval.
  - `409` `already_rolled_back` if current version matches target.

### 3. Request Feedback Boost
- **Method/Path**: `POST /v1/signals/{signal_id}/feedback-requests`
- **Description**: Enqueue samples for human review with rubric assignment.
- **Request Body**:
```json
{
  "sample_ids": ["req_97f2", "req_97f3"],
  "rubric": ["correctness", "empathy"],
  "annotator_group": "support-specialists",
  "sla_minutes": 180,
  "notes": "Focus on billing responses"
}
```
- **Response (201)**:
```json
{
  "status": "success",
  "data": {
    "feedback_request_id": "fbk_1204",
    "signal_id": "Signal-1280",
    "samples_enqueued": 2,
    "due_at": "2024-06-05T12:22:10Z",
    "status": "pending"
  },
  "trace_id": "trc_f01"
}
```
- **Errors**:
  - `400` `invalid_samples` when sample IDs are not owned by signal.
  - `409` `duplicate_request` if same sample already pending.

### 4. Release Gate Evaluation
- **Method/Path**: `POST /v1/signals/{signal_id}/release-gate/check`
- **Description**: Evaluate whether signal can be promoted given guardrail thresholds; used by CI/CD.
- **Request Body**:
```json
{
  "metrics": {
    "net_eval_score": 4.2,
    "hallucination_rate": 0.07,
    "latency_p95_ms": 910
  },
  "context": {
    "deployment": "prod",
    "requestor": "ci_pipeline_28"
  }
}
```
- **Response (200)**:
```json
{
  "status": "success",
  "data": {
    "can_promote": false,
    "blocking_rules": [
      {
        "rule_id": "guardrail_hallucination_prod",
        "message": "Hallucination rate above threshold (5%)"
      }
    ],
    "recommendations": ["Queue auto-rerun", "Request annotation review"]
  },
  "trace_id": "trc_f42"
}
```
- **Errors**:
  - `404` `not_found` if signal unknown.
  - `422` `invalid_metrics` if required metrics missing.

### 5. Incident Acknowledge & Resolve
- **Method/Path**: `PATCH /v1/incidents/{incident_id}`
- **Description**: Update incident state post-action.
- **Request Body**:
```json
{
  "status": "resolved",
  "resolved_reason": "Rollback completed",
  "resolution_notes": "Rollback deployed, rerun confirms metrics recovered",
  "linked_actions": ["deploy_993a", "rr_57c9"]
}
```
- **Response (200)**:
```json
{
  "status": "success",
  "data": {
    "incident_id": "inc_812",
    "status": "resolved",
    "resolved_at": "2024-06-05T10:05:00Z"
  },
  "trace_id": "trc_f88"
}
```

Webhook Notifications
---------------------
- **Event Types**: `rerun.started`, `rerun.completed`, `rollback.started`, `rollback.completed`, `feedback_request.created`, `release_gate.blocked`.
- **Delivery**: Signed POST to configured URL containing event envelope (same schema as ingestion).
- **Retry**: Exponential backoff up to 5 attempts; `X-Signature` header with HMAC SHA256.

Idempotency & Concurrency
-------------------------
- Clients should provide `X-Request-Id`; server returns `409 duplicate_request` when same id reused within 10 minutes.
- Rollback endpoint enforces single active job per workflow; subsequent calls return the existing deployment job info.

Security Considerations
-----------------------
- Role-based access: only users with `ai.operator` role can trigger rollback; rerun allowed for `ai.engineer`.
- Audit log entry created for every POST/PATCH described above.
- Tokens scoped per workflow to prevent cross-tenant actions.
