"""Phase 4, graph 1: pre-meeting briefing. Read-only; rules pick health and products."""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.graphs import briefing
from app.db.seed import sid
from app.models import ApprovalItem, AuditEvent
from tests.conftest import login

PEARL = sid("company", "pearl-bay")  # licence expiring in under 30 days
DUNES = sid("company", "dunes-logistics")  # holds an LC line, no FX line


def _facts(**over: Any) -> dict[str, Any]:
    today = date(2026, 11, 23)
    wc = str(uuid.uuid4())
    base: dict[str, Any] = {
        "today": today.isoformat(),
        "company": {"id": str(uuid.uuid4())},
        "facilities": [
            {
                "id": wc,
                "product": "WORKING_CAPITAL",
                "limit": "100",
                "utilized": "50",
                "weekly": [],
            },
            {
                "id": str(uuid.uuid4()),
                "product": "CASH_MANAGEMENT",
                "limit": "1",
                "utilized": "0",
                "weekly": [],
            },
        ],
        "snapshots": [
            {
                "id": str(uuid.uuid4()),
                "period_end": "2026-10-31",
                "revenue": "1000",
                "ebitda": "150",
                "interest_expense": "10",
                "principal_repayment": "40",
                "avg_bank_balance": "300",
                "bounced_cheques": 0,
            }
        ],
        "documents": [
            {
                "id": str(uuid.uuid4()),
                "doc_type": t,
                "expiry_date": None,
                "verification_status": "VERIFIED",
            }
            for t in [
                "TRADE_LICENSE",
                "CR_CERTIFICATE",
                "UBO_DECLARATION",
                "FINANCIAL_STATEMENT",
                "BANK_STATEMENT",
            ]
        ],
        "open_signals": [],
    }
    base.update(over)
    return base


def test_healthy_account_with_everything_on_file() -> None:
    m = briefing.compute_metrics(_facts())
    assert m["health"] == "GOOD" and m["gaps"] == []
    assert m["dscr_latest"] == "3.0000" and m["product_candidates"] == []


def test_weak_cover_or_serious_alert_is_a_concern() -> None:
    weak = _facts()
    weak["snapshots"][0]["ebitda"] = "55"  # DSCR 1.1
    assert briefing.compute_metrics(weak)["health"] == "CONCERN"
    alert = _facts(open_signals=[{"id": str(uuid.uuid4()), "severity": "HIGH"}])
    assert briefing.compute_metrics(alert)["health"] == "CONCERN"


def test_hot_line_or_expiring_document_is_worth_watching() -> None:
    hot = _facts()
    hot["facilities"][0]["utilized"] = "90"
    assert briefing.compute_metrics(hot)["health"] == "WATCH"
    expiring = _facts()
    expiring["documents"][0]["expiry_date"] = (date(2026, 11, 23) + timedelta(days=20)).isoformat()
    m = briefing.compute_metrics(expiring)
    assert m["health"] == "WATCH"
    assert m["gaps"] == [
        {
            "kind": "expiring",
            "doc_type": "TRADE_LICENSE",
            "days_left": 20,
            "id": expiring["documents"][0]["id"],
        }
    ]


def test_product_ideas_follow_the_metrics() -> None:
    f = _facts()
    wc = f["facilities"][0]
    weeks = [date(2026, 11, 23) - timedelta(weeks=w) for w in range(9, -1, -1)]
    wc["weekly"] = [{"as_of": d.isoformat(), "utilized": "90"} for d in weeks]  # 63 days above 85%
    f["facilities"].append(
        {
            "id": str(uuid.uuid4()),
            "product": "TRADE_FINANCE_LC",
            "limit": "100",
            "utilized": "10",
            "weekly": [],
        }
    )
    ideas = briefing.compute_metrics(f)["product_candidates"]
    assert [i["product"] for i in ideas] == ["TERM_LOAN", "FX_LINE"]
    assert "63 days" in ideas[0]["reason"] and ideas[0]["source_record_ids"] == [wc["id"]]


async def test_briefing_runs_read_only_to_completion(
    client: AsyncClient, session: AsyncSession
) -> None:
    await login(client, "rm@demo.local")
    r = await client.post(f"/api/agents/briefing/{PEARL}")
    assert r.status_code == 202, r.text
    run = (await client.get(f"/api/agent-runs/{r.json()['id']}")).json()
    assert run["status"] == "COMPLETED"
    nodes = [e["node"] for e in run["trace"] if e["type"] == "node"]
    assert nodes == ["fetch_account_context", "compute_health_metrics", "synthesize_briefing"]
    assert "interrupt" not in {e["type"] for e in run["trace"]}

    result = run["result"]
    assert result["metrics"]["health"] in {"WATCH", "CONCERN"}
    gaps = result["briefing"]["gaps"]
    assert any(g.startswith("The trade licence expires in") for g in gaps)
    assert len(result["briefing"]["talking_points"]) >= 2
    assert {c["kind"] for c in run["cited_records"]} >= {"Account", "Facility", "Document"}

    # Read-only: no proposals, and the only audit event is the start.
    n = await session.scalar(
        select(func.count())
        .select_from(ApprovalItem)
        .where(ApprovalItem.agent_run_id == uuid.UUID(run["id"]))
    )
    assert n == 0
    actions = list(
        await session.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == run["id"]))
    )
    assert actions == ["agent.started"]


async def test_lc_customer_without_fx_line_gets_an_fx_idea(client: AsyncClient) -> None:
    await login(client, "compliance@demo.local")  # read-only agent: any role may run it
    r = await client.post(f"/api/agents/briefing/{DUNES}")
    run = (await client.get(f"/api/agent-runs/{r.json()['id']}")).json()
    pitched = [p["product"] for p in run["result"]["briefing"]["product_ideas"]]
    assert "FX_LINE" in pitched
    assert (await client.post(f"/api/agents/briefing/{uuid.uuid4()}")).status_code == 404


async def test_pitches_for_products_the_rules_did_not_propose_are_dropped(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def overreach(ctx: dict[str, Any]) -> briefing.Briefing:
        good = briefing._mock(ctx)
        extra = briefing.ProductPitch(
            product="IJARA", pitch="Lease the new delivery fleet with an Ijara."
        )  # type: ignore[arg-type]
        return good.model_copy(update={"product_ideas": [*good.product_ideas, extra][-2:]})

    monkeypatch.setitem(llm._MOCK_HANDLERS, briefing.TASK, overreach)
    await login(client, "rm@demo.local")
    r = await client.post(f"/api/agents/briefing/{DUNES}")
    run = (await client.get(f"/api/agent-runs/{r.json()['id']}")).json()
    assert run["status"] == "COMPLETED"
    assert "IJARA" not in [p["product"] for p in run["result"]["briefing"]["product_ideas"]]
    dropped = next(e for e in run["trace"] if e.get("name") == "drop_unsupported_pitches")
    assert "IJARA" in dropped["input"]["proposed"] and "IJARA" not in dropped["output"]["kept"]
