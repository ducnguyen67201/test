REPO INSPECTION - minimal runbook

Date: 2025-11-30T08:42:25Z

Purpose: single-file checklist to know where to look when working on OctoLab backend runtime/teardown issues.

Key files and why they matter:
- app/main.py - FastAPI app entry; how the app is run and config loaded.
- app/config.py - runtime config & env-based switches.
- app/db.py - DB session maker and helper functions (crucial for transaction patterns).
- app/models/lab.py - Lab ORM model (status fields, finished_at, owner_id)
- app/services/teardown_worker.py - worker that claims and tears down labs (primary target for ENDING hang fixes).
- app/runtime/compose_runtime.py - compose-specific runtime actions (destroy_lab, resource checks)
- app/runtime/k8s_runtime.py - k8s runtime actions and differences vs compose.
- app/services/lab_service.py / orchestrator_service.py - higher level lifecycle orchestration.
- app/scripts/force_teardown_ending_labs.py - admin script to force teardown (example usage of teardown logic).

Tests to inspect (unit/integration):
- backend/tests/test_teardown_worker.py
- backend/tests/test_ending_reconcile.py
- backend/tests/test_teardown_timeout.py
- backend/tests/test_ending_watchdog.py

Runtime tools and places to check:
- Docker/compose: docker ps, docker compose -p octolab_<lab_id> ps
- Database: check long-running transactions (ps aux | grep postgres or use psql: SELECT pid, state, query_start FROM pg_stat_activity WHERE state <> 'idle'); identify "idle in transaction" sessions holding SELECT FOR UPDATE locks.
- Logs: uvicorn stdout (app logs) and worker logs; look for exceptions referencing teardown_worker.

Common failure modes and quick actions:
- idle in transaction blocking updates: find process in pg_stat_activity, kill it if safe, and refactor code to avoid long transactions across external calls.
- resources missing but lab stuck ENDING: implement resources_exist check and reconcile to FINISHED without calling destroy.
- subprocess hangs: ensure subprocess calls use timeouts and shell=False.

Useful commands:
- Run tests: (from /backend) pytest -q
- Run specific test: pytest backend/tests/test_ending_reconcile.py::test_missing_resources_reconciles -q
- Inspect DB locks: sudo -u postgres psql -c "SELECT pid, usename, state, query, query_start FROM pg_stat_activity ORDER BY query_start DESC LIMIT 50;"
- Inspect docker for lab: docker ps -a --filter "name=octolab_<lab_id>" --format "{{.ID}}" || true

Notes on privacy/safety:
- Do not log owner_id, tokens, or secrets. Log only lab_id when reconciling.

Where this file lives: backend/REPO_INSPECTION.md (checked by the agent on future tasks).