# SPEC — Open MSME CRM

An open-source, agentic CRM for **MSME (micro, small and medium enterprise) corporate banking**, with
human-in-the-loop (HITL) controls on every AI action.

This is a **reference implementation and demo**, not a production banking system. It runs on synthetic
data only. Read section 9 (non-goals) before deploying anything.

---

## 1. Problem and users

MSME relationship managers (RMs) carry 100–300+ business accounts. They lose time to messy financial
documents, KYB renewals, slow credit memo drafting, and late detection of cash-flow stress.

Three roles, enforced on the server:

| Role | Does |
|---|---|
| `RM` | Manages accounts, pipeline, outreach; starts agent runs; approves outreach and task proposals. |
| `CREDIT_OFFICER` | Reviews financial health and credit memos; resolves early-warning alerts. |
| `COMPLIANCE` | Reviews KYB/UBO discrepancies and compliance flags; reads the audit trail. |
| `ADMIN` | Everything, for demos and setup. |

---

## 2. Stack (pinned majors)

Monorepo: `/backend`, `/frontend`, root `docker-compose.yml`.

**Backend** — Python 3.12, FastAPI, Pydantic v2 + `pydantic-settings`, managed with **uv** only.
- PostgreSQL 16 (Docker Compose). Async SQLAlchemy 2.x with `asyncpg`. Alembic migrations.
- LangGraph 1.x with `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`).
- LLM providers behind one interface: `mock` (default), `anthropic`, `openai_compatible`
  (any OpenAI-compatible base URL: vLLM, Ollama, LM Studio, a hosted gateway).
- Server-Sent Events via `sse-starlette` for agent progress.
- Auth: JWT in an HTTP-only cookie, argon2 password hashing (`pwdlib`), RBAC as FastAPI dependencies.

**Frontend** — React 19, TypeScript (strict), Vite, React Router, Tailwind CSS v4, shadcn/ui-style
components, lucide-react icons, Recharts, TanStack Query, and a typed client generated from the
backend's `/openapi.json` with `openapi-typescript` + `openapi-fetch`.

**Tests** — pytest + pytest-asyncio + httpx against a real Postgres test database; Vitest; Playwright
for end-to-end flows (Phase 5).

---

## 3. Data model

UUID primary keys everywhere. Timezone-aware UTC timestamps. **Money is `Numeric(18, 2)`, ratios and
rates are `Numeric(10, 4)`, and Python code uses `Decimal` — never `float`.**

Every company carries an ISO 4217 `currency`. Seed data uses GCC currencies (BHD, SAR, AED, KWD, OMR,
QAR); the default is set by `DEFAULT_CURRENCY`.

- **User** — email, full name, `role`, branch, hashed password, active flag.
- **Company** (MSME account) — legal name, trading name, commercial registration (`cr_number`,
  unique), country (ISO 3166 alpha-2), industry (ISIC section), tier (`MICRO`, `SMALL`, `MEDIUM`),
  annual turnover, currency, internal risk rating (1–10), `kyb_status` (`VERIFIED`,
  `PENDING_RENEWAL`, `FLAGGED`), next KYB review date, assigned RM.
- **BeneficialOwner** — company, name, nationality, ownership % (`Numeric(5, 2)`), is-UBO flag
  (computed against `UBO_THRESHOLD_PCT`, default 25), PEP status, sanctions status.
- **Contact** — company, name, title, email, phone, primary flag.
- **Facility** — company, product (`WORKING_CAPITAL`, `TERM_LOAN`, `TRADE_FINANCE_LC`,
  `LETTER_OF_GUARANTEE`, `POS_MERCHANT`, `FX_LINE`, `CASH_MANAGEMENT`, `MURABAHA`, `IJARA`),
  `is_islamic`, sanctioned limit, current utilised amount, profit/interest rate, start and maturity
  dates, covenants (JSONB list of `{metric, operator, threshold}`).
- **FacilityUtilization** — facility, `as_of` date, utilised amount. Weekly history, so time-based
  rules ("above 90% for 30+ days") can be computed.
- **FinancialSnapshot** — company, period end, period type (`MONTHLY`, `ANNUAL`), and **raw inputs
  only**: revenue, EBITDA, net profit, interest expense, principal repayment, total debt, total
  equity, current assets, current liabilities, average bank balance, bounced cheque count.
  **No stored ratios.** DSCR, leverage and current ratio are always computed by
  `financial_math.py` from these inputs.
- **Deal** — company, product, stage (`LEAD`, `QUALIFICATION`, `DOC_COLLECTION`,
  `CREDIT_UNDERWRITING`, `APPROVAL`, `DISBURSED`, `LOST`), requested amount, probability %, expected
  close date, owner RM, draft CAM (JSONB, nullable).
- **Document** — company, optional deal, type (`TRADE_LICENSE`, `CR_CERTIFICATE`,
  `FINANCIAL_STATEMENT`, `BANK_STATEMENT`, `TAX_RETURN`, `UBO_DECLARATION`), file name, expiry date,
  verification status (`PENDING`, `VERIFIED`, `REJECTED`), extracted fields (JSONB).
- **Interaction** — company, user, type (`CALL`, `MEETING`, `EMAIL`, `SITE_VISIT`), occurred at,
  summary, notes.
- **Task** — company, optional deal, assignee, title, due date, status (`OPEN`, `DONE`), source
  (`MANUAL`, `AGENT`).
- **EarlyWarningSignal** — company, trigger (`CASHFLOW_DROP`, `UTILIZATION_SPIKE`, `DOC_EXPIRY`,
  `BOUNCED_CHEQUES`, `COVENANT_BREACH`), severity (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), status
  (`OPEN`, `INVESTIGATING`, `RESOLVED`), the metric values that fired it (JSONB), AI root-cause
  summary, detected at, resolved by/at.
- **AgentRun** — `thread_id` (the LangGraph thread), optional `parent_run_id`, agent name,
  triggered by, company/deal, status (`RUNNING`, `AWAITING_APPROVAL`, `COMPLETED`, `FAILED`,
  `REJECTED`), `trace` (JSONB: ordered node events, tool inputs/outputs, cited record ids, latency,
  token usage), timestamps.
- **ApprovalItem** — agent run, `thread_id`, `idempotency_key` (**unique**), action type
  (`SEND_EMAIL`, `CREATE_TASK`, `ESCALATE_EWS`, `SUBMIT_CAM`, `FLAG_KYB`, `UPDATE_KYB_RECORD`),
  proposed payload, edited payload, status (`PENDING`, `APPROVED`, `EDITED_AND_APPROVED`,
  `REJECTED`), `initiator_id`, `reviewer_id`, review note, resolved at.
- **OutboxMessage** — approved outbound messages. Status `SIMULATED` only: this project never sends
  real email.
- **AuditEvent** — **append-only**: actor (user or agent), action, entity type/id, payload,
  `prev_hash`, `hash` (SHA-256 over prev hash + canonical JSON of the event). A Postgres trigger
  rejects `UPDATE` and `DELETE` on this table.

### LangGraph tables

The checkpointer's tables live in a separate Postgres schema, `langgraph`, created by
`checkpointer.setup()`. Alembic's `env.py` only manages the `public` schema (`include_name` /
`include_object` filters), so autogenerate never proposes dropping checkpointer tables.

---

## 4. Agent layer

Four LangGraph workflows, checkpointed with `AsyncPostgresSaver` so a paused run survives restarts.

### 4.1 Guardrails (all agents)

1. **HITL as three nodes.** Any path that changes business state or prepares outbound communication
   uses this shape:
   - `propose_<action>` — upserts the `ApprovalItem` on its `idempotency_key`
     (`{thread_id}:{action}:{target_id}`). No other side effects.
   - `await_<action>` — contains **only** `interrupt(...)`. LangGraph re-runs the interrupted node
     from the top on resume, so nothing with side effects may live in this node.
   - `apply_<action>` — runs only on `APPROVED` / `EDITED_AND_APPROVED`, using the edited payload if
     present.
   Resume happens only through `POST /api/approvals/{id}/resolve`, which calls the graph with
   `Command(resume={"decision": ..., "payload": ...})`.
2. **Four-eyes.** For `SUBMIT_CAM`, `ESCALATE_EWS`, `FLAG_KYB` and `UPDATE_KYB_RECORD`, the reviewer
   must not be the initiator, and must hold the right role (`CREDIT_OFFICER` for credit and EWS,
   `COMPLIANCE` for KYB). The server enforces this, and a test proves it.
3. **Deterministic numbers.** Ratios, utilisation, balance changes, covenant tests and thresholds
   come only from pure, unit-tested functions in `app/services/financial_math.py`. The LLM narrates
   numbers it is given and never computes them.
4. **Structured, cited output.** Every LLM step returns a Pydantic model with
   `source_record_ids: list[UUID]`. Unknown ids are rejected before anything is saved.
5. **Untrusted documents.** Text extracted from uploaded files is data, not instructions. The
   extraction node has no tools that write. Extracted values pass schema validation and range checks
   before reconciliation.
6. **No real outbound actions.** Approved emails go to `OutboxMessage` with status `SIMULATED`.
7. **Audit everything.** Every node transition and tool call is appended to `AgentRun.trace`. Every
   approval decision and state change writes an `AuditEvent`.
8. **Mock mode is the real system.** With `LLM_PROVIDER=mock` (default), the real graphs,
   checkpointer, tools and interrupt/resume run end to end. Only the LLM call returns deterministic
   output. Tests and CI use mock mode.
9. **Data residency.** Seed data is synthetic. The README warns against sending real customer data to
   an external model and documents `openai_compatible` for self-hosted models.

### 4.2 The four graphs

**Graph 1 — Pre-meeting briefing and next-best-product** (read-only, no interrupt)
`POST /api/agents/briefing/{company_id}` (SSE).
`fetch_account_context` → `compute_health_metrics` (deterministic) → `synthesize_briefing`.
Output: account health, talking points, open document/compliance gaps, and 1–2 product ideas tied to
specific metrics (e.g. working capital utilisation above 85% for 8 weeks → limit review or term-out;
regular FX volume → FX forward line; seasonal balance dips → Murabaha working capital).

**Graph 2 — KYB and document intake**
`POST /api/documents/upload` starts it.
`parse_document` → `extract_fields` (LLM, no write tools) → `validate_fields` → `reconcile_against_db`
(licence/CR expiry, UBOs at or above the threshold, revenue/EBITDA against the latest snapshot) →
if discrepancies: `propose_kyb_actions` → `await_kyb_review` → `apply_kyb_actions`; else
`mark_verified`.
Mock mode supports `.txt` and `.json` "documents"; PDF text extraction uses `pypdf`.

**Graph 3 — Early-warning portfolio scan**
`POST /api/agents/ews-scan` (button) and a CLI entry point for cron
(`uv run python -m app.jobs.ews_scan`).
Parent graph: `scan_portfolio` (deterministic rules) → `create_ews_records` → fan out **one child
thread per flagged company**. Each child: `analyse_root_cause` → `draft_outreach` →
`propose_outreach` → `await_outreach` → `apply_outreach` (outbox message or call task). One approval
per company, resolved independently.
Rules (all thresholds in settings):
- average bank balance down more than 25% over the last 2 monthly snapshots → `CASHFLOW_DROP`
- working capital utilisation above 90% on every weekly point for the last 30+ days → `UTILIZATION_SPIKE`
- any bounced cheques in the latest month → `BOUNCED_CHEQUES`
- trade licence or CR expiring within 30 days → `DOC_EXPIRY`
- any facility covenant failing on the latest snapshot → `COVENANT_BREACH`

**Graph 4 — Credit appraisal memo (CAM) drafting**
`POST /api/agents/cam/{deal_id}`, only for deals in `CREDIT_UNDERWRITING`.
`gather_deal_and_exposure` → `calculate_ratios` (deterministic, including pro-forma DSCR with the
new facility) → `fetch_benchmarks` (static industry table in seed data) → `draft_cam_sections`
(executive summary, business overview, financial analysis, facility structure, risks and mitigants,
preliminary risk grade — all cited) → `propose_cam_submission` → `await_cam_review` →
`apply_cam_submission` (moves the deal to `APPROVAL` and assigns a credit officer).

---

## 5. Screens

1. **Command centre** (`/`) — KPIs (total limits, utilisation, pipeline value, open EWS), "needs your
   approval" list, upcoming document expiries, "run portfolio scan" with live progress.
2. **Accounts** (`/accounts`, `/accounts/:id`) — searchable list; 360° view with tabs (overview,
   facilities and utilisation, financials with charts, owners and documents, interactions, EWS
   history) and a slide-over co-pilot panel for briefings.
3. **Pipeline** (`/deals`) — kanban and table views, deal drawer with document checklist and
   "draft credit memo".
4. **Risk radar** (`/risk`) — EWS table by severity, the metric values that fired, resolution.
5. **Approvals and audit** (`/approvals`, `/audit`) — proposed action with edit / approve / reject;
   an inspection drawer showing the run's node trace, tool inputs/outputs and cited records; audit log
   with hash-chain verification status.

Every view handles loading, empty and error states.

---

## 6. Seed data

`uv run python -m app.db.seed` — idempotent (deterministic UUIDs from names, upserts).
- 4 users: one per role, password from `SEED_PASSWORD` (default `demo1234`, development only).
- 15 synthetic companies in Bahrain, Saudi Arabia, UAE, Kuwait, Oman and Qatar, across manufacturing,
  wholesale trade, logistics, healthcare clinics, F&B and construction; turnover equivalent to roughly
  USD 250k–15M. All names are invented.
- Facilities (conventional and Islamic), 26 weeks of utilisation, 6 monthly snapshots, owners,
  contacts, documents, interactions and deals across every stage.
- Five planted anomalies, each on a different company: a licence expiring in under 30 days; a 30%+
  balance drop; working capital above 92% for 6 weeks; bounced cheques; a UBO ownership mismatch
  between the UBO declaration document and the database.

---

## 7. Phases

Each phase ends with all checks in CLAUDE.md green and a short summary, then stops for review.

- **Phase 1 — Foundation.** Docker Compose, FastAPI app factory, settings, all SQLAlchemy models,
  initial Alembic migration (including the audit trigger and the schema filter), seed script, auth
  (login, logout, `/me`, dev persona switch), RBAC dependency, audit-event writer with hash chain,
  read-only `/api/accounts` list. Frontend shell: login, persona switcher, navigation, placeholder
  pages, generated API types, accounts list wired to the API. Tests for auth, RBAC, seed idempotency,
  audit chain and the append-only trigger.
- **Phase 2 — Core CRM.** Endpoints and screens for accounts 360°, pipeline, facilities and
  financials charts, documents, interactions, tasks. `financial_math.py` with full test coverage.
- **Phase 3 — Agent infrastructure.** Checkpointer in the lifespan, LLM provider interface with mock,
  `AgentRun` tracing, approval endpoints with four-eyes rules, SSE, approvals screen and inspection
  drawer, audit trail screen. A small development-only demo agent (propose one follow-up task)
  exercises the full loop before the four main graphs exist.
- **Phase 4 — The four graphs.** One graph per session, each with tests for the happy path, interrupt,
  approve / edit-and-approve / reject, idempotent proposals, and trace persistence.
- **Phase 5 — Polish.** Playwright flows (scan → approve outreach → resolve; deal → draft CAM → edit
  → submit → credit officer review), error states, README screenshots, GitHub Actions CI.

---

## 8. Configuration

All settings come from environment variables via `pydantic-settings`; `.env.example` lists every one.
Key ones: `ENVIRONMENT`, `DATABASE_URL`, `CHECKPOINT_DATABASE_URL`, `JWT_SECRET`,
`LLM_PROVIDER` (`mock` | `anthropic` | `openai_compatible`), `LLM_MODEL`, `LLM_BASE_URL`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEFAULT_CURRENCY`, `UBO_THRESHOLD_PCT`, EWS thresholds.

---

## 9. Non-goals

- Not production banking software: no SSO, no core-banking integration, no real email, no
  regulatory certification, no claim of compliance with any regulator's rules.
- No real customer data. Ever.
- Credit decisions are always made by people; the system only drafts and routes.
