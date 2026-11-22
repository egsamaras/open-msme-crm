"""Phase 2: account 360°, facilities, financials, documents, interactions, tasks, pipeline."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.db.seed import sid
from tests.conftest import login

FALCON = sid("company", "falcon-steel")
DUNES = sid("company", "dunes-logistics")
PEARL = sid("company", "pearl-bay")
GULF = sid("company", "gulf-spice")


async def test_account_detail_flags_ubos(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    acc = (await client.get(f"/api/accounts/{GULF}")).json()
    assert acc["trading_name"] == "Gulf Spice"
    pcts = [Decimal(o["ownership_pct"]) for o in acc["owners"]]
    assert pcts == sorted(pcts, reverse=True)
    # At or above the 25% threshold counts as a UBO.
    assert all(o["is_ubo"] == (Decimal(o["ownership_pct"]) >= 25) for o in acc["owners"])
    assert acc["contacts"][0]["is_primary"] is True


async def test_unknown_account_is_404(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    r = await client.get("/api/accounts/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


async def test_financials_compute_ratios_from_raw_inputs(client: AsyncClient) -> None:
    await login(client, "credit@demo.local")
    rows = (await client.get(f"/api/accounts/{DUNES}/financials")).json()
    assert len(rows) == 6
    latest = rows[-1]
    service = Decimal(latest["interest_expense"]) + Decimal(latest["principal_repayment"])
    expected = (Decimal(latest["ebitda"]) / service).quantize(Decimal("0.0001"))
    assert Decimal(latest["dscr"]) == expected
    assert rows[0]["balance_change_pct"] is None
    # The planted cash-flow drop: balance falls sharply over the last two months.
    assert Decimal(rows[-2]["avg_bank_balance"]) > Decimal(rows[-1]["avg_bank_balance"])
    two_month = (
        Decimal(rows[-1]["avg_bank_balance"]) / Decimal(rows[-3]["avg_bank_balance"]) - 1
    ) * 100
    assert two_month < -25


async def test_facilities_show_sustained_utilisation_and_covenants(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    facilities = (await client.get(f"/api/accounts/{FALCON}/facilities")).json()
    wc = next(f for f in facilities if f["product"] in ("WORKING_CAPITAL", "MURABAHA"))
    assert len(wc["history"]) == 26
    assert Decimal(wc["utilization_pct"]) > 92
    assert wc["days_above_alert_threshold"] >= 35  # six weekly points above 90%
    term = next(f for f in facilities if f["product"] not in ("WORKING_CAPITAL", "MURABAHA"))
    assert term["days_above_alert_threshold"] == 0


async def test_covenant_results_are_tested_against_latest_snapshot(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    accounts = (await client.get("/api/accounts")).json()
    found = []
    for a in accounts:
        for f in (await client.get(f"/api/accounts/{a['id']}/facilities")).json():
            found.extend(f["covenants"])
    assert found, "seed has DSCR covenants on term loans and Ijara"
    c = found[0]
    assert c["metric"] == "DSCR"
    assert c["passes"] == (Decimal(c["actual"]) >= Decimal(c["threshold"]))


async def test_documents_include_the_expiring_licence(client: AsyncClient) -> None:
    await login(client, "compliance@demo.local")
    docs = (await client.get(f"/api/accounts/{PEARL}/documents")).json()
    licence = next(d for d in docs if d["doc_type"] == "TRADE_LICENSE")
    days = (date.fromisoformat(licence["expiry_date"]) - datetime.now(UTC).date()).days
    assert 0 < days < 30


async def test_log_interaction(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    when = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    body = {"interaction_type": "CALL", "occurred_at": when, "summary": "Discussed renewal"}
    r = await client.post(f"/api/accounts/{FALCON}/interactions", json=body)
    assert r.status_code == 201
    assert r.json()["user_name"] == "Layla Rahman"
    listed = (await client.get(f"/api/accounts/{FALCON}/interactions")).json()
    assert listed[0]["summary"] == "Discussed renewal"


async def test_interaction_in_the_future_is_rejected(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    body = {"interaction_type": "CALL", "occurred_at": when, "summary": "Time travel"}
    r = await client.post(f"/api/accounts/{FALCON}/interactions", json=body)
    assert r.status_code == 422


async def test_tasks_only_the_assignee_can_complete(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    r = await client.post("/api/tasks", json={"company_id": str(FALCON), "title": "Call CFO"})
    assert r.status_code == 201
    task = r.json()
    assert task["assignee_name"] == "Layla Rahman"
    assert any(t["id"] == task["id"] for t in (await client.get("/api/tasks")).json())

    await login(client, "compliance@demo.local")
    r = await client.patch(f"/api/tasks/{task['id']}", json={"status": "DONE"})
    assert r.status_code == 403

    await login(client, "rm@demo.local")
    r = await client.patch(f"/api/tasks/{task['id']}", json={"status": "DONE"})
    assert r.status_code == 200
    assert r.json()["status"] == "DONE"
    open_tasks = (await client.get(f"/api/accounts/{FALCON}/tasks?status=OPEN")).json()
    assert task["id"] not in [t["id"] for t in open_tasks]


async def _deal_in(client: AsyncClient, stage: str) -> dict[str, object]:
    deals = (await client.get("/api/deals", params={"stage": stage})).json()
    assert deals, f"seed has a deal in {stage}"
    return dict(deals[0])


async def test_deal_detail_has_document_checklist(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    deal = await _deal_in(client, "DOC_COLLECTION")
    detail = (await client.get(f"/api/deals/{deal['id']}")).json()
    states = {i["doc_type"]: i["state"] for i in detail["checklist"]}
    assert states["TRADE_LICENSE"] == "VERIFIED"
    assert states["FINANCIAL_STATEMENT"] == "MISSING"
    assert detail["checklist_complete"] is False
    assert "APPROVAL" not in detail["allowed_stages"]


async def test_rm_moves_deal_and_probability_follows(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    deal = await _deal_in(client, "LEAD")
    r = await client.patch(f"/api/deals/{deal['id']}", json={"stage": "QUALIFICATION"})
    assert r.status_code == 200
    assert r.json()["stage"] == "QUALIFICATION"
    assert r.json()["probability_pct"] == 25


async def test_rm_cannot_skip_to_approval(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    deal = await _deal_in(client, "CREDIT_UNDERWRITING")
    r = await client.patch(f"/api/deals/{deal['id']}", json={"stage": "APPROVAL"})
    assert r.status_code == 409
    assert "credit memo" in r.json()["detail"]


async def test_compliance_cannot_edit_deals(client: AsyncClient) -> None:
    await login(client, "compliance@demo.local")
    deal = await _deal_in(client, "QUALIFICATION")
    r = await client.patch(f"/api/deals/{deal['id']}", json={"probability_pct": 90})
    assert r.status_code == 403


async def test_credit_officer_disburses_approved_deal_only(client: AsyncClient) -> None:
    await login(client, "credit@demo.local")
    open_deal = await _deal_in(client, "DOC_COLLECTION")
    r = await client.patch(f"/api/deals/{open_deal['id']}", json={"stage": "QUALIFICATION"})
    assert r.status_code == 409
    r = await client.patch(f"/api/deals/{open_deal['id']}", json={"probability_pct": 50})
    assert r.status_code == 403

    approved = await _deal_in(client, "APPROVAL")
    r = await client.patch(f"/api/deals/{approved['id']}", json={"stage": "DISBURSED"})
    assert r.status_code == 200
    assert r.json()["probability_pct"] == 100
    assert r.json()["allowed_stages"] == []


async def test_create_deal_is_rm_only(client: AsyncClient) -> None:
    body = {
        "company_id": str(PEARL),
        "title": "Pearl Bay — LC line",
        "product": "TRADE_FINANCE_LC",
        "requested_amount": "50000.00",
    }
    await login(client, "compliance@demo.local")
    assert (await client.post("/api/deals", json=body)).status_code == 403
    await login(client, "rm@demo.local")
    r = await client.post("/api/deals", json=body)
    assert r.status_code == 201
    assert r.json()["stage"] == "LEAD"
    assert r.json()["currency"] == "BHD"
