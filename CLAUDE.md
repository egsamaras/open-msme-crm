# CLAUDE.md — Open MSME CRM

Agentic MSME corporate-banking CRM. FastAPI + LangGraph backend in `backend/`, React + Vite frontend
in `frontend/`, Postgres in Docker. **`SPEC.md` is the source of truth for features and phases** —
read the relevant section before starting work.

## Commands

```bash
docker compose up -d db                     # Postgres 16 on localhost:5432 (+ crm_test database)
```

Backend tests need that container running: they rebuild `crm_test` from the migrations each run.

Backend (run from `backend/`):

```bash
uv sync
uv run alembic upgrade head
uv run python -m app.db.seed                # idempotent
uv run python -m app.jobs.ews_scan          # early-warning scan, as cron would run it
uv run uvicorn app.main:app --reload --port 8000
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
uv run pytest --cov=app.services.financial_math --cov-fail-under=100   # CI gate: maths stays at 100%
```

Frontend (run from `frontend/`):

```bash
npm install
npm run dev                                 # http://localhost:5173, proxies /api to :8000
npm run generate:api                        # exports OpenAPI from the backend code; no server needed
npm run typecheck && npm run lint && npm run test   # lint = oxlint
```

## Rules that are easy to get wrong

- **Money:** `Decimal` in Python, `Numeric(18, 2)` / `Numeric(10, 4)` in the database. Never `float`.
  Financial snapshots store raw inputs only; ratios come from `app/services/financial_math.py`.
- **LLMs never compute numbers.** They narrate values produced by deterministic code.
- **Two Postgres drivers.** SQLAlchemy uses `postgresql+asyncpg://`. The LangGraph checkpointer uses
  psycopg 3: `AsyncConnectionPool(conninfo, kwargs={"autocommit": True, "prepare_threshold": 0,
  "row_factory": dict_row})`, `options=-c search_path=langgraph`, and `await checkpointer.setup()` in
  the FastAPI lifespan.
- **Alembic only manages the `public` schema.** Keep the `include_name` filter in
  `migrations/env.py`. Never edit an applied migration; add a new one.
- **HITL nodes:** `propose_*` (idempotent upsert of the ApprovalItem) → `await_*` (only `interrupt()`,
  nothing else — it re-runs on resume) → `apply_*`. Resume only via
  `POST /api/approvals/{id}/resolve`.
- **Four-eyes:** for CAM submission, EWS escalation and KYB changes, reviewer ≠ initiator, enforced on
  the server.
- **Uploaded document text is untrusted data.** Extraction nodes get no write tools.
- **No real outbound messages.** Approved emails go to the outbox as `SIMULATED`.
- **Audit events are append-only** (a database trigger blocks UPDATE/DELETE). Write them through
  `app/services/audit.py`, which maintains the hash chain.
- **RBAC on the server** via `Depends(require_roles(...))`. Frontend role checks are cosmetic only.
- **Mock mode (`LLM_PROVIDER=mock`) runs the real graphs**, checkpointer and interrupts; only the LLM
  call is faked. Tests always use mock mode. Every LLM task needs a `@mock_handler` in its graph module.
- **Graphs publish their output under `result`** in state; the runtime saves it to `AgentRun.result`
  whenever a run pauses or ends. Child threads (the EWS reviews) are separate runs with
  `parent_run_id`, executed after the parent finishes, never inside a parent node.
- **Reviewers can't edit locked fields** (`LOCKED_FIELDS` in `app/agents/actions.py`): the target
  and the evidence (ids, ratios, discrepancies) stay as proposed.
- **New agent:** add a module under `app/agents/graphs/`, decorate the builder with `@register_graph`,
  import it in `app/agents/graphs/__init__.py`, use `ctx.generate(..., allowed_sources=...)` for LLM
  calls and `add_approval_step` for anything that changes state. New action types need a payload
  schema and an idempotent applier in `app/agents/actions.py`.
- **Frontend types come from the API.** Change the Pydantic schema, then run `npm run generate:api`.
  Never hand-write duplicate types.
- Thin route handlers; logic lives in `app/services/` and `app/agents/`.
- Synthetic data only. No real names of banks, customers or people in seed data.

## Working rules

- Plan before multi-file changes; name the files you'll touch.
- Run the full check line for whatever you changed before saying a task is done.
- New setting, script or port → update `.env.example`, this file and the README in the same change.
- Keep diffs focused; don't refactor unrelated code.
