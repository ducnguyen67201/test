# Temporal Workflow Service – Engineering Spec

## 1. Goal & Scope
- Build a dedicated Go service in `apps/queue` that owns Temporal workflows/activities for long-running lab provisioning and evaluation flows.
- Provide a single registry for all task queues so engineers can add workflows/activities in one place.
- Integrate with existing lab lifecycle state machine (`apps/api/internal/domain/entity/lab_request.go:26-37`) and use case logic (`apps/api/internal/usecase/lab_usecase.go:223`) without leaking Temporal concerns into the domain layer.
- Deliver local development parity by extending `docker-compose.yml` with Temporal core + UI so `docker compose up` brings up Postgres, Redis, and Temporal.

## 2. High-Level Architecture
1. **Temporal Cluster** (local via Docker; prod via managed/self-hosted) exposes namespace `zerozero-dev`, gRPC at `7233`, UI at `8233`.
2. **Queue Service (apps/queue)**  
   - Owns Temporal worker processes, workflow/activity code, and shared Temporal client factory.  
   - Publishes Go module `github.com/zerozero/apps/queue`.  
   - Ships a worker binary (`cmd/worker/main.go`) that registers all workflows/activities at startup by consulting a central registry.
3. **API Service (apps/api)**  
   - On `ConfirmRequest`, calls Temporal via injected client to `ExecuteWorkflow`, storing the workflow ID + run ID on the `lab_requests` row.  
   - HTTP handlers query workflow status via use case and optionally Temporal queries/signals.

## 3. Directory Layout (new)
```
apps/queue/
  go.mod
  cmd/
    worker/
      main.go          # loads config, builds DI container, starts worker(s)
  internal/
    config/
      config.go        # mirrors apps/api/pkg/config but focuses on Temporal + logging
    temporal/
      client.go        # shared client factory (gRPC options, metrics, TLS)
      registry/
        registry.go    # central RegisterAll entry-point
    workflows/
       labs/
        registrar.go          # implements registry.Registrar
        labs.workflow.go      # LabProvisionWorkflow definition
        labs.activities.go    # adapters to blueprint service, python runner, etc.
        labs.queries.go       # strongly-typed workflow queries/signals
    adapters/
      services/
        blueprint.go   # wraps apps/api/internal/infrastructure/services BlueprintService calls
      persistence/
        lab_repository.go # thin wrapper to reuse existing lab repo interfaces over gRPC/HTTP
  pkg/
    logger/
    metrics/
```

## 4. Configuration & Environment
- Add a `TemporalConfig` struct to `apps/api/pkg/config/config.go` and a matching one in `apps/queue/internal/config`. Fields:
  - `Address` (`TEMPORAL_ADDRESS`, default `localhost:7233`)
  - `Namespace` (`TEMPORAL_NAMESPACE`, default `zerozero-dev`)
  - `LabsTaskQueue` (`TEMPORAL_LABS_TASK_QUEUE`, default `labs.provisioning.v1`)
  - `WorkerIdentity` (`TEMPORAL_WORKER_IDENTITY`, default `queue-worker`)
  - TLS flags (`TEMPORAL_TLS_ENABLED`, cert/key paths, CA cert)
- Worker binary loads `.env.local` the same way `apps/api/internal/app/config.go:26-52` does, then instantiates logger + Temporal client.
- Document CLI helper commands (`temporal namespace describe`, `temporal workflow list`) in this spec and README once implemented.

## 5. Central Registry Pattern
- Define `type Registrar interface { TaskQueue() string; Register(w worker.Worker) }`.
- Create `registry.RegisterAll(worker.Worker, []Registrar)` to loop through registrars, filtering by task queue so different task queues can run in different processes.
- Each workflow package exports `func NewRegistrar(deps *Dependencies) registry.Registrar` to capture dependencies (repos, services, config) without globals.
- Prefer explicit file names combining domain + concern (`labs.workflow.go`, `labs.activities.go`, `labs.queries.go`) so grep/logging makes intent obvious when multiple workflows live side-by-side.
- Worker startup:
  ```go
  registrars := []registry.Registrar{
      labs.NewRegistrar(labsDeps),
      // future registrars...
  }
  registry.RegisterAll(workerInstance, registrars...)
  ```
- New workflows only require adding files + appending to the registrar slice inside `cmd/worker/main.go`.

## 6. Workflow Design (Labs MVP)
1. **`LabProvisionWorkflow`**
   - Input: `LabProvisionParams{LabID string, RequestedBy string, Severity entity.LabSeverity, TTLHours int}`.
   - Steps:
     1. `activities.LockLab(labID)` – marks the row as “queued” (idempotent).
     2. `activities.GenerateBlueprint(labID)` – calls existing blueprint service (`services.NewMockBlueprintService` initially).
     3. `activities.ProvisionEnvironment(labID)` – triggers Python service or infra API and heartbeats progress.
     4. `activities.RunValidation(labID)` – runs automated checks; handles retries/backoff.
     5. `activities.RequestHumanReview(labID)` – optional child workflow / signal waiting step for manual approval (aligns with Feedback Lens queue).
     6. `activities.FinalizeLab(labID)` – updates DB to `running` or `completed` and emits events.
   - Uses workflow queries to expose `CurrentPhase`, `PercentComplete` for UI.
2. **Signals / Queries**
   - `CancelLabSignal` – invoked when API receives `CancelLab` for queued/running labs (`apps/api/internal/usecase/lab_usecase.go:37,429`).
   - `HumanReviewSignal` – invoked when human reviewer approves/resolves step 5.

## 7. Integration Points
- **API Service (`apps/api`)**
  - Inject Temporal client instance into `LabUseCase` (new constructor argument).  
   - `ConfirmRequest`:
     ```go
     run, err := temporalClient.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
         ID:        fmt.Sprintf("lab-%s", lab.ID),
         TaskQueue: cfg.Temporal.LabsTaskQueue,
    }, workflows.LabProvisionWorkflow, workflows.LabProvisionParams{...})
     lab.WorkflowID = run.GetID()
     lab.RunID = run.GetRunID()
     ```
  - `CancelLab` – send workflow signal if workflow ID exists, fall back to legacy behavior if not.
- **Python Service / External Runners**
  - Expose HTTP/gRPC endpoints consumed by activities. Activities stay idempotent by storing external job IDs in Temporal memo/search attributes.
- **Shared Types**
  - Keep workflow/activity DTOs in `apps/queue/internal/workflows/labs/types.go`; import domain enums from `github.com/zerozero/apps/api/internal/domain/entity`.

## 8. Observability & Reliability
- Enable Temporal metrics exporter (Prometheus) and point it at the existing stack described in `docs/business_proposal/03_ui_architecture.md:214`.
- Attach logging interceptor so each activity logs `lab_id`, `phase`, `attempt`.
- Configure retry policies per activity (max attempts, backoff) instead of manual loops. Use `workflow.GetVersion` for backward-compatible changes.
- Add unit tests using `go.temporal.io/sdk/testsuite` for workflows and `testify/suite` for activities.

## 9. Local Development Flow
1. Run `docker compose up postgres redis temporal temporal-ui` (Temporal services added to the root compose file).
2. Create namespace once: `temporal operator namespace create --namespace zerozero-dev`.
3. Start the worker: `cd apps/queue && go run ./cmd/worker`.
4. Start the API: `cd apps/api && go run ./cmd/server`.
5. Trigger workflows via existing HTTP endpoints; inspect progress at `http://localhost:8233`.

## 10. Phased Implementation Plan
1. **Infra foundation**
   - Add Temporal services to `docker-compose.yml`.
   - Scaffold `apps/queue` module, config loader, logger wrapper.
2. **Workflow skeleton**
   - Implement registry + worker binary with placeholder Lab workflow/activities that log steps.
   - Add Temporal client to API service but keep flag-guarded (env var) to fall back to current flows.
3. **End-to-end lab provisioning**
   - Replace placeholders with real activities (blueprint generation, Python orchestrator, DB updates).
   - Store workflow IDs on lab records, add cancellation signals, wire UI status chips to workflow queries.
4. **Advanced features**
   - Human-in-the-loop signals, metrics dashboards, task queue autoscaling hooks (KEDA/HPA on queue depth).

## 11. Open Questions / Decisions
| Topic | Options | Notes |
| --- | --- | --- |
| Temporal hosting | Temporal Cloud vs self-hosted | Start local docker; production decision pending cost/SOC2 needs. |
| Activity auth | Direct DB access vs REST | Foreshadowed adapters assume REST/gRPC to avoid cross-service DB writes; confirm preferred approach. |
| Namespace strategy | single vs per-env | Recommend per environment (`zerozero-dev`, `zerozero-stg`, `zerozero-prod`). |
| Workflow data retention | 30 vs 90 days | Default 30-day retention; adjust after storage sizing. |

This spec provides the blueprint for implementing Temporal-driven background workflows in `apps/queue` while keeping the rest of the system aligned with existing clean-architecture boundaries.
