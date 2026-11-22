from httpx import AsyncClient

from tests.conftest import login


async def test_me_requires_sign_in(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_login_sets_cookie_and_me_works(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    me = (await client.get("/api/auth/me")).json()
    assert me["role"] == "RM"
    assert "password_hash" not in me


async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    r = await client.post("/api/auth/login", json={"email": "rm@demo.local", "password": "nope"})
    assert r.status_code == 401


async def test_login_is_case_insensitive_on_email(client: AsyncClient) -> None:
    await login(client, "RM@Demo.Local")


async def test_logout_clears_session(client: AsyncClient) -> None:
    await login(client, "rm@demo.local")
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_tampered_token_is_rejected(client: AsyncClient) -> None:
    client.cookies.set("crm_session", "not-a-jwt")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_dev_persona_switch(client: AsyncClient) -> None:
    personas = (await client.get("/api/auth/personas")).json()
    assert {p["role"] for p in personas} == {"RM", "CREDIT_OFFICER", "COMPLIANCE", "ADMIN"}
    credit = next(p for p in personas if p["role"] == "CREDIT_OFFICER")
    r = await client.post("/api/auth/dev-switch", json={"user_id": credit["id"]})
    assert r.status_code == 200
    assert (await client.get("/api/auth/me")).json()["role"] == "CREDIT_OFFICER"


async def test_session_endpoint_is_200_when_signed_out(client: AsyncClient) -> None:
    r = await client.get("/api/auth/session")
    assert r.status_code == 200
    assert r.json() == {"user": None}
    await login(client, "rm@demo.local")
    assert (await client.get("/api/auth/session")).json()["user"]["role"] == "RM"
