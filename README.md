# Open MSME CRM

**An open-source, agentic CRM for MSME corporate banking, where AI drafts and people decide.**

Relationship managers who serve small and medium businesses carry hundreds of accounts. Much of
their day goes to chasing documents, re-keying financials, drafting credit memos and spotting
trouble too late. This project shows how AI agents can take that work on **without ever acting
alone**: every action an agent proposes waits in an approval queue for a person to edit, approve
or reject it, and every step is written to a tamper-evident audit trail.

> **Status: Phase 1 of 5 (foundation).** Data model, migrations, synthetic GCC portfolio, auth
> and roles, audit chain, and the app shell work today. The agents arrive in Phases 3–4 — see the
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

## The four agents (Phases 3–4)

1. **Pre-meeting briefing** — account health, talking points, open gaps and next-best-product ideas
   tied to specific metrics. Read-only.
2. **KYB and document intake** — extracts fields from uploaded documents, reconciles owners and
   financials against the record, and routes discrepancies to compliance.
3. **Early-warning scan** — deterministic rules (balance drops, sustained utilisation, bounced
   cheques, expiring licences, covenant breaches), then one drafted outreach per flagged client,
   each approved separately.
4. **Credit memo drafting** — ratios and pro-forma DSCR from code, sections drafted with citations,
   RM edits, then four-eyes submission to a credit officer.

## Stack

FastAPI · SQLAlchemy 2 (async) · Alembic · PostgreSQL 16 · LangGraph with a Postgres checkpointer ·
React 19 · TypeScript · Vite · Tailwind CSS v4 · TanStack Query · types generated from OpenAPI.

## Quick start

You need Docker, [uv](https://docs.astral.sh/uv/) and Node.js 22+.

```bash
git clone <this repo> open-msme-crm && cd open-msme-crm
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
- [ ] **Phase 2 — Core CRM:** account 360°, pipeline, financial charts, documents, interactions, tasks.
- [ ] **Phase 3 — Agent infrastructure:** checkpointer, LLM providers, tracing, approvals with four-eyes, inspection drawer.
- [ ] **Phase 4 — The four agents.**
- [ ] **Phase 5 — Polish:** Playwright end-to-end flows, screenshots.

## Non-goals

- Not production banking software: no SSO, no core-banking integration, no real email, no
  regulatory certification, and no claim of compliance with any regulator's rules.
- No real customer data, ever. If you point it at an external model, don't send it real data.
- Credit decisions are always made by people. The system drafts and routes; it never approves.

## License

[Apache 2.0](LICENSE).
