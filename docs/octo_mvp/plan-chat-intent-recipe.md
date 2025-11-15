# LLM Chat-to-Recipe Spec

## Problem Statement
- Users currently have to describe desired testing/mimic environments manually; the backend only exposes CRUD recipes (`apps/octolab_mvp/backend/app/schemas/recipe.py`) and assumes well-formed requests.
- We need a conversational workflow where an LLM captures user intent, translates it into a structured recipe payload, and triggers downstream image builds that provision the requested environment.
- Requirement: **keep a check** (cost + safety guardrails) so that generated recipes and builds stay within supported software stacks and policy.

## Goals
1. Provide a guided chat UI where product engineers describe their target environment in natural language and get incremental clarifying questions from the LLM.
2. Persist the complete conversation, extracted intents, and generated recipes so that they can be audited and replayed.
3. Automatically convert post-chat summaries into the existing `Recipe` model (name, description, software, version_constraint, exploit_family, activation state) plus any new build metadata needed to produce container/VM images.
4. **Current scope**: stop after the LLM produces a validated JSON payload that mirrors `RecipeCreate`; backend systems consume that payload to trigger builds later.
5. **Future scope**: kick off the build pipeline (Linux targets first) once the recipe is approved, while emitting checkpoints/alerts if the LLM proposes unsupported components.
6. Keep token usage, build minutes, and guardrail violations under control ("keep a check").

Non-Goals (v1)
- Live editing of running environments inside chat.
- Automated vendor-specific deployment (focus on building and storing images; manual push to clouds later).

## Key Personas
- **Product engineer / QA**: describes environment (e.g., “Banking app that depends on jQuery 2.1 and Oracle 12c”).
- **LLM Orchestrator**: internal service that manages the conversation + intent extraction prompts.
- **Recipe Builder**: background worker that converts recipes to actual base images / dockerfiles and pushes artifacts to the Linux build registry.

## High-Level Architecture
1. **Front-end (apps/web)**: Chat surface with session state, streaming assistant messages, and “Finish & Generate Recipe” action.
2. **Conversation Service (backend FastAPI)**:
   - POST `/chat/sessions` -> create session (ties to org/user).
   - POST `/chat/sessions/{id}/messages` -> proxy to LLM, store both sides.
   - POST `/chat/sessions/{id}/finalize` -> run summarization + intent extraction chain.
3. **LLM Orchestrator**:
   - Primary model (gpt-4o / claude) for interactive chat.
   - Secondary deterministic prompt that returns structured JSON (Intent Payload).
   - Safety validator to “keep a check” using restricted vocab lists + heuristics.
4. **Recipe Service**:
   - Transforms intent payload into `RecipeCreate`.
   - Persists recipe record, attaches `build_plan`.
5. **Build Pipeline (apps/queue)**:
   - Enqueues `BuildRecipeJob`.
   - Worker reads job, constructs environment (Dockerfile template library + custom steps).
   - Push image to Linux target registry, update build status.
6. **Observability / Guardrail Layer**:
   - Track tokens, inference cost, rejected intents.
   - Flag high-risk software (e.g., outdated runtimes, malware) before build.

## Detailed Flow
1. **Session Initialization**
   - `POST /chat/sessions` with optional `project_id`.
   - Response: `session_id`, streaming URL, allowed capabilities (metadata from policy service).
2. **Message Exchange**
   - Frontend sends user messages via WebSocket/Server-Sent Events.
   - Backend stores each message: `ChatMessage(id, session_id, role, content, tokens)`.
   - LLM responses streamed back; include clarifying questions to capture requirements (OS, runtime versions, dependencies, compliance needs).
3. **Completion Trigger**
   - User clicks “Generate Recipe”.
   - Backend closes session and calls `IntentExtractor` with full transcript + instructions to summarize requirements and produce JSON.
4. **Intent Extraction Prompt (deterministic)**
   - Template instructs model to output:
     ```json
     {
       "name": "...",
       "description": "...",
       "software": "primary stack",
       "version_constraint": "semver or OS label",
       "exploit_family": "if relevant (banking PCI, healthcare HIPAA, etc.)",
       "is_active": true,
       "os": "ubuntu2204",
       "packages": [{"name": "node", "version": "16.20"}],
       "network_requirements": "...",
       "compliance_controls": ["pci", "sox"],
       "validation_checks": ["run regression suite X"],
       "confidence": 0-1
     }
     ```
   - "Keep a check": run schema validation, hard cap on package count, check version whitelist, and call a policy evaluator microservice. Reject/flag if:
     - Unknown OS/base image.
     - Banned software versions.
     - Confidence < 0.6 or missing required fields.
   - Deliverable for current milestone: validated JSON persisted in `intents.payload` and returned to frontend/download endpoint; backend automation reads it later.
5. **Recipe Persistence (Phase 2+)**
   - Map JSON -> `RecipeCreate` fields.
   - Store extended metadata in a new table `recipe_build_plans` (FK to recipe, JSON `build_plan`, status enum).
   - Emit `RecipeCreated` event for audit.
6. **Build Kickoff (Phase 2+)**
   - Push job to queue with recipe_id, os, packages.
   - Worker uses template library (Dockerfile fragments per OS) to create build context, then uses Pack/Docker to build and push to Linux registry.
   - Update plan status transitions: `queued -> building -> success/failed`.
7. **Feedback to User**
   - For Phase 1 return the JSON payload, validator result, and instructions for backend ingestion; later phases return recipe summaries + build job IDs.
   - Frontend shows progress (poll or subscribe to job status) once build orchestration is available.
   - Provide "Request change" button to reopen chat seeded with previous transcript if build fails.

## Example Scenario: Apache CVE Request
1. **User states the need**
   - "I want to test my application on Apache that contains CVE-2342. Please build on Ubuntu 22.04, include OpenSSL 1.1.1, and ship with PCI controls."
2. **LLM probing + summarizing**
   - Assistant asks for exact Apache version, exploit tooling requirements, networking constraints, and activation preference; user responds with Apache 2.4.49, CVE-2019-0234 exploitation kit v1, isolated network, and wants the recipe marked active.
3. **Generated payload (Phase 1 output)**
   ```json
   {
     "name": "Apache CVE-2019-0234 Regression Rig",
     "description": "Ubuntu 22.04 target with Apache 2.4.49 + exploit harness for QA banking portal.",
     "software": "apache-httpd",
     "version_constraint": "2.4.49",
     "exploit_family": "banking-pci",
     "is_active": true,
     "os": "ubuntu2204",
     "packages": [
       {"name": "apache2", "version": "2.4.49"},
       {"name": "openssl", "version": "1.1.1"},
       {"name": "mod_security", "version": "2.9"},
       {"name": "cve-2019-0234-kit", "version": "1.0"}
     ],
     "network_requirements": "isolated vlan, outbound disabled",
     "compliance_controls": ["pci"],
     "validation_checks": [
       "run exploit kit smoke test",
       "verify read-only mock db"
     ],
     "confidence": 0.82
   }
   ```
4. **Handoff**
   - Chat service stores the payload, exposes it to the frontend/backend in JSON, and the downstream recipe builder (outside Phase 1 scope) consumes it to call `RecipeCreate` and kick off infrastructure work.

## Data Model Changes
1. `chat_sessions`
   - `id UUID PK`, `user_id`, `project_id`, `status (open|finalizing|closed)`, `llm_model`, `token_usage`.
2. `chat_messages`
   - `id`, `session_id FK`, `role (user|assistant|system)`, `content TEXT`, `sequence`, `tokens`, `created_at`.
3. `intents`
   - `id`, `session_id`, `payload JSONB`, `confidence`, `status (draft|approved|rejected)`, `validator_errors`.
4. `recipes` (existing)
   - No schema change required for MVP, reuse `name/description/software/version_constraint/exploit_family/is_active`.
5. `recipe_build_plans`
   - `recipe_id FK`, `os`, `packages JSONB`, `network_requirements`, `compliance_controls`, `build_status`, `artifact_uri`.

## API Contract Sketch
- `POST /chat/sessions`
  - Body: `{project_id?, llm_model?}`
  - Response: `{session_id, stream_url}`
- `POST /chat/sessions/{id}/messages`
  - Body: `{content}`
  - SSE/WebSocket stream returns assistant deltas.
- `POST /chat/sessions/{id}/finalize`
  - Response: `{intent_id, confidence, validation:{passed, errors[]}}`
- `POST /chat/intents/{id}/approve`
  - Body: `{auto_build: true|false}`
  - Response: `{recipe_id, build_plan_id}`
- `GET /recipes/{id}/build_plan`
  - Shows job + artifact status.

## Frontend Requirements
1. Chat UI with streaming output, ability to display system hints (“Please provide OS”).
2. Transcript viewer after session closes.
3. Intent summary panel: highlight extracted packages, compliance needs, validation status, toggle to edit before approval.
4. Build tracker card linking to recipe detail page.
5. Guardrail messaging: if validator rejects request, show reasons + CTA to revise.

## Guardrails (“Keep a Check”)
- **LLM Prompt Controls**: include system prompt with allowed OS/stack list, require explicit confirmation for sensitive software.
- **Validator Service**: deterministic script + policy config file (YAML) listing allowed packages, banned CVEs.
- **Rate & Cost Limits**: session-level budget (max tokens, max duration). Stop chat if exceeded.
- **Audit Logging**: capture transcripts, decisions, and build outputs for compliance.
- **Human-in-the-loop**: optional manual approval workflow if compliance flag triggered.

## Telemetry & Observability
- Metrics: `chat_sessions_total`, `intent_confidence_avg`, `recipes_from_chat`, `build_failures`.
- Alerts: high failure rate, repeated banned requests, slow build durations.
- Logging: structured logs with session and recipe IDs.

## Acceptance Criteria
1. Users can complete an end-to-end chat that produces a stored recipe and enqueued build job.
2. Intent JSON adheres to schema; invalid requests are blocked with meaningful feedback (UI + API).
3. Conversation transcripts, intents, recipes, and build plans are all queryable for audit.
4. Guardrail policies enforce allowed OS/software versions; attempts to exceed budgets or policies are logged and surfaced.
5. Build pipeline produces Linux-ready artifacts accessible via artifact URI in the recipe detail view.

## Open Questions
1. Which LLM provider/model (OpenAI, Anthropic, local) do we standardize on? Need latency + cost comparison.
2. Do we require manual approval for all recipes or only flagged cases?
3. What is the SLA for build completion, and do we need retry/backoff logic?
4. Should compliance tags map directly to `exploit_family` or do we need a new field?
5. How are secrets (license keys, repo URLs) provided securely to the build worker?

## Next Steps
1. Finalize data model migration scripts (`chat_sessions`, `chat_messages`, `intents`, `recipe_build_plans`).
2. Define prompt templates + JSON schema for intents; add golden transcripts for testing.
3. Implement chat API + WebSocket streaming endpoint in FastAPI.
4. Build frontend chat interface within `apps/web` using existing design system.
5. Wire queue worker to consume `BuildRecipeJob` and integrate with Linux registry.
