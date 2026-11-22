from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.models import User
from app.schemas.common import LoginIn, PersonaSwitchIn, SessionOut, UserOut
from app.services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
    s = get_settings()
    response.set_cookie(
        s.cookie_name,
        create_access_token(user.id, user.role),
        max_age=s.access_token_minutes * 60,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, response: Response, session: SessionDep) -> User:
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    _set_session_cookie(response, user)
    await audit.record(
        session, action="auth.login", entity_type="user", entity_id=user.id, actor_user_id=user.id
    )
    await session.commit()
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(get_settings().cookie_name, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.get("/session", response_model=SessionOut)
async def current_session(request: Request, session: SessionDep) -> SessionOut:
    """Who is signed in, or `user: null`. Unlike /me, signed-out is a normal 200 answer."""
    try:
        user = await get_current_user(request, session)
    except HTTPException:
        return SessionOut(user=None)
    return SessionOut(user=UserOut.model_validate(user))


@router.get("/personas", response_model=list[UserOut])
async def personas(session: SessionDep) -> list[User]:
    """Development only: the seeded users the persona switcher can become."""
    if not get_settings().is_dev:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    rows = await session.scalars(select(User).where(User.is_active).order_by(User.role))
    return list(rows)


@router.post("/dev-switch", response_model=UserOut)
async def dev_switch(body: PersonaSwitchIn, response: Response, session: SessionDep) -> User:
    """Development only: sign in as a seeded persona without a password."""
    if not get_settings().is_dev:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    user = await session.get(User, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
    _set_session_cookie(response, user)
    await audit.record(
        session,
        action="auth.dev_switch",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
    )
    await session.commit()
    return user
