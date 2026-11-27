"""Phase 4, graph 1: pre-meeting briefing. Read-only; rules pick health and products."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.graphs import briefing
from app.db.seed import sid
from app.models import ApprovalItem, AuditEvent
from app.models.enums import DocumentType, VerificationStatus
from tests.conftest import login

PEARL = sid("company", "pearl-bay")  # licence expiring in under 30 days
DUNES = sid("company", "dunes-logistics")  # holds an LC line, no FX line

TODAY = date(2026, 11, 23)
LICENCE, CERTIFICATE = DocumentType.TRADE_LICENSE, DocumentType.CR_CERTIFICATE
PENDING, REJECTED = VerificationStatus.PENDING, VerificationStatus.REJECTED
ON_FILE = [
    LICENCE,
    CERTIFICATE,
    DocumentType.UBO_DECLARATION,
    DocumentType.FINANCIAL_STATEMENT,
    DocumentType.BANK_STATEMENT,
]


def _doc(
    doc_type: DocumentType,
    days: int | None = None,
    state: VerificationStatus = VerificationStatus.VERIFIED,
    added: int = 0,
) -> Any:
    """A document expiring `days` after TODAY (None: undated), added `added` hours after others."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        doc_type=doc_type,
        file_name=f"{doc_type.value.lower()}.pdf",
        expiry_date=None if days is None else TODAY + timedelta(days=days),
        verification_status=state,
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=added),
    )


def _facts(*docs: Any, **over: Any) -> dict[str, Any]:
    """An account with every required document on file, verified and undated, plus `docs`."""
    wc = str(uuid.uuid4())
    base: dict[str, Any] = {
        "today": TODAY.isoformat(),
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
        "documents": briefing.document_facts([_doc(t) for t in ON_FILE] + list(docs)),
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
    licence = _doc(LICENCE, 20)
    m = briefing.compute_metrics(_facts(licence))
    assert m["health"] == "WATCH"
    assert m["gaps"] == [
        {
            "kind": "expiring",
            "doc_type": "TRADE_LICENSE",
            "days_left": 20,
            "id": str(licence.id),
        }
    ]


# Only the licence or certificate in force can be expiring, by the rule the Accounts list and the
# early-warning scan use: for each type, the verified document that expires last.


def _gaps(*docs: Any) -> tuple[str, list[tuple[str, str]]]:
    """Health, and the kind and document id of each gap, with `docs` on file too."""
    m = briefing.compute_metrics(_facts(*docs))
    return m["health"], [(g["kind"], g["id"]) for g in m["gaps"]]


def test_a_verified_renewal_removes_the_expiring_gap() -> None:
    old = _doc(LICENCE, 20)
    assert _gaps(old) == ("WATCH", [("expiring", str(old.id))])
    assert _gaps(old, _doc(LICENCE, 400, added=1)) == ("GOOD", [])


def test_a_pending_renewal_leaves_the_old_licence_expiring() -> None:
    old, renewal = _doc(LICENCE, 20), _doc(LICENCE, 400, PENDING, added=1)
    # The renewal is a gap of its own until it's verified.
    assert _gaps(old, renewal) == (
        "WATCH",
        [("expiring", str(old.id)), ("pending", str(renewal.id))],
    )


def test_a_rejected_upload_due_soon_adds_no_expiring_gap() -> None:
    rejected = _doc(LICENCE, 3, REJECTED, added=1)
    # Its rejection is the only gap, with or without a dated, verified licence on file.
    assert _gaps(_doc(LICENCE, 400), rejected) == ("GOOD", [("rejected", str(rejected.id))])
    assert _gaps(rejected) == ("GOOD", [("rejected", str(rejected.id))])


def test_only_the_licence_and_certificate_in_force_can_expire() -> None:
    licence, certificate = _doc(LICENCE, 5), _doc(CERTIFICATE, 50)
    # Other types have no validity period here, even if the KYB check read a date off one.
    others = [_doc(DocumentType.BANK_STATEMENT, 2), _doc(DocumentType.UBO_DECLARATION, 10)]
    assert _gaps(licence, certificate, *others) == (
        "WATCH",
        [("expiring", str(licence.id)), ("expiring", str(certificate.id))],
    )


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
