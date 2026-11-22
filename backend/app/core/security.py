import uuid
from datetime import timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.models.base import utcnow
from app.models.enums import Role

_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


def create_access_token(user_id: uuid.UUID, role: Role) -> str:
    s = get_settings()
    now = utcnow()
    claims = {
        "sub": str(user_id),
        "role": role.value,
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    s = get_settings()
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
