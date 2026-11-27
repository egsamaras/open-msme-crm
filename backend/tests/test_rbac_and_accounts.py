import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from tests.conftest import login


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("rm@demo.local", 403),
        ("credit@demo.local", 403),
        ("compliance@demo.local", 200),
        ("admin@demo.local", 200),
    ],
)
async def test_audit_verify_is_compliance_only(
    client: AsyncClient, email: str, expected: int
) -> None:
    await login(client, email)
    assert (await client.get("/api/audit/verify")).status_code == expected


async def test_accounts_need_sign_in(client: AsyncClient) -> None:
    assert (await client.get("/api/accounts")).status_code == 401


async def test_accounts_list(client: AsyncClient) -> None:
    await login(client, "credit@demo.local")
    rows = (await client.get("/api/accounts")).json()
    assert len(rows) == 15
    first = rows[0]
    assert {r["rm_name"] for r in rows} == {"Layla Rahman", "Yusuf Darwish"}
    assert float(first["total_limit"]) > 0
    assert {r["currency"] for r in rows} == {"BHD", "SAR", "AED", "KWD", "OMR", "QAR"}


async def test_accounts_search(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    rows = (await client.get("/api/accounts", params={"q": "falcon"})).json()
    assert [r["trading_name"] for r in rows] == ["Falcon Steel"]


async def test_persona_switch_is_hidden_outside_development(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "environment", "test")
    assert (await client.get("/api/auth/personas")).status_code == 404
