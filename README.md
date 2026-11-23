# Open MSME CRM

[![CI](https://github.com/egsamaras/open-msme-crm/actions/workflows/ci.yml/badge.svg)](https://github.com/egsamaras/open-msme-crm/actions/workflows/ci.yml)

**An open-source, agentic CRM for MSME corporate banking, where AI drafts and people decide.**

Relationship managers who serve small and medium businesses carry hundreds of accounts. Much of
their day goes to chasing documents, re-keying financials, drafting credit memos and spotting
trouble too late. This project shows how AI agents can take that work on **without ever acting
alone**: every action an agent proposes waits in an approval queue for a person to edit, approve
or reject it, and every step is written to a tamper-evident audit trail.

> **Status: Phase 4 of 5 done.** All four agents work end to end in mock mode: the briefing
> co-pilot, KYB document intake, the early-warning portfolio scan and credit memo drafting, each
> with live progress, cited output and (where anything changes) a human approval with server-side
> four-eyes rules. Phase 5 adds browser end-to-end tests and screenshots — see the
> [roadmap](#roadmap).
>
> **Reference implementation, not production banking software.** Synthetic data only. See
> [non-goals](#non-goals).

## What makes it different

| Principle | How it's enforced |
|---|---|
| **Humans approve every consequential action** | LangGraph `interrupt()` before any write or outbound message; resume only through the approvals API. |
| **Four-eyes on credit and compliance** | For credit memo submission, risk escalation and KYB changes the reviewer must be a different person with the right role — checked on the server. |
| **The LLM never does the maths** | DSCR, leverage, utilisation and covenant tests come from tested `Decimal` code. Snapshots store raw inputs only, never pre-computed ratios. |
| **Every claim is cited** | Agent outputs carry the ids of the database records they used; unknown ids are rejected. |
| **Tamper-evident audit** | Append-only table (a Postgres trigger blocks UPDATE, DELETE and TRUNCATE), with a SHA-256 hash chain you can verify. |
| **Untrusted documents stay untrusted** | Text pulled from uploaded files is treated as data; the extraction step has no tools that write. |
| **Runs without an API key** | Mock mode runs the real graphs, checkpointer and approvals with deterministic LLM output. Swap in Anthropic, or any OpenAI-compatible endpoint (vLLM, Ollama) to keep data in-house. |

## The four agents

1. **Pre-meeting briefing** — account health, talking points, open gaps and up to two product
   ideas. Fixed rules choose the health status and which products to suggest (for example a
   working-capital line above 85% for eight weeks suggests a limit review or term-out); the model
   only writes them up, and a pitch for any other product is dropped. Read-only.
2. **KYB and document intake** — upload a `.txt`, `.json` or `.pdf`; the model extracts fields with
   no tools that write, then fixed rules validate them and reconcile CR number, expiry, owners and
   financials against the record. Clean documents are verified; differences go to a compliance
   officer as a register update or a KYB flag (four-eyes).
3. **Early-warning scan** — fixed rules (balance drop over two months, working capital above 90%
   for 30+ days, bounced cheques, licence or CR expiring, covenant breaches) find the signals; each
   flagged company gets its own agent thread that explains the likely cause and drafts a follow-up.
   High or critical signals go to a credit officer as an escalation (four-eyes); others become a
   simulated email or a call task for the RM. Also runs from cron.
4. **Credit memo drafting** — ratios, pro-forma DSCR with the new facility and an indicative
   scorecard grade come from code, benchmarks from a static table; the model drafts six cited
   sections. A credit officer who didn't start the run edits and approves it, which moves the deal
   to Approval and makes them its credit officer.

## Stack

FastAPI · SQLAlchemy 2 (async) · Alembic · PostgreSQL 16 · LangGraph with a Postgres checkpointer ·
React 19 · TypeScript · Vite · Tailwind CSS v4 · TanStack Query · types generated from OpenAPI.

## Quick start

You need Docker, [uv](https://docs.astral.sh/uv/) and Node.js 22+.

```bash
git clone https://github.com/egsamaras/open-msme-crm.git && cd open-msme-crm
docker compose up -d db
```

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in as `rm@demo.local`, `credit@demo.local` or
`compliance@demo.local` with password `demo1234`. In development, the **View as** menu switches
persona without signing out.

A five-minute tour (use **View as** to switch persona):

1. **Risk radar** as the RM: press **Run portfolio scan**. Four planted anomalies fire; each
   company's review streams in and waits in **Approvals**. Approve or edit the simulated emails.
2. As the **credit officer**, approve the escalations for Dunes Freight and Oasis Clinics. The
   alerts move to "investigating" and both of you get tasks.
3. **Pipeline** as the RM: open Gulf Spice (credit underwriting) and press **Draft credit memo**.
   As the credit officer, edit a section in **Approvals** and approve; the deal moves to Approval.
4. **Accounts → Gulf Spice → Owners & documents** as the RM: **Run KYB check** on the pending UBO
   declaration. As compliance, review the ownership changes and approve.
5. Any account: **Prepare briefing**. Then open **Audit trail** as compliance and re-check the
   hash chain.

**Inspect what the agent did** on any run shows each step, every tool input and output, and the
records the model cited.

The scan also runs from cron: `uv run python -m app.jobs.ews_scan` (from `backend/`).

Copy `.env.example` to `.env` to change anything; every setting has a safe development default.

## Synthetic portfolio

15 invented companies across Bahrain, Saudi Arabia, the UAE, Kuwait, Oman and Qatar, in local
currencies, with conventional and Islamic facilities (Murabaha, Ijara), six months of financials,
26 weeks of utilisation, owners, documents, interactions and a pipeline. Five anomalies are planted
for the agents to find: an expiring trade licence, a sharp balance drop, sustained high utilisation,
bounced cheques, and a UBO declaration that disagrees with the record.

## Development

```bash
# backend
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
# frontend
npm run typecheck && npm run lint && npm run test
npm run generate:api        # regenerate TypeScript types after changing an API schema
```

Backend tests run against a real Postgres database (`crm_test`, created by Docker Compose): they
apply the real migrations and seed, and check that the schema matches the models.

[`SPEC.md`](SPEC.md) is the full specification. [`CLAUDE.md`](CLAUDE.md) holds the working rules
for AI coding assistants (and humans) contributing to the repo.

## Roadmap

- [x] **Phase 1 — Foundation:** schema and migrations, seed, auth and roles, audit chain, app shell.
- [x] **Phase 2 — Core CRM:** account 360°, pipeline, financial charts, documents, interactions, tasks, tested financial maths.
- [x] **Phase 3 — Agent infrastructure:** checkpointer, LLM providers (mock, Anthropic, OpenAI-compatible), tracing, approvals with four-eyes, live run stream, inspection drawer, audit trail page, demo agent.
- [x] **Phase 4 — The four agents:** briefing co-pilot, KYB intake, early-warning scan with one thread per flagged company, credit memo with four-eyes submission; Risk radar page.
- [ ] **Phase 5 — Polish:** Playwright end-to-end flows, screenshots.

## Non-goals

- Not production banking software: no SSO, no core-banking integration, no real email, no
  regulatory certification, and no claim of compliance with any regulator's rules.
- No real customer data, ever. If you point it at an external model, don't send it real data.
- Credit decisions are always made by people. The system drafts and routes; it never approves.

## License

[Apache 2.0](LICENSE).
