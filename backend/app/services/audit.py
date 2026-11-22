"""Append-only, hash-chained audit log (SPEC 3, AuditEvent).

Each event's hash is SHA-256 over the previous hash plus the canonical JSON of the event.
Appends take a transaction-scoped advisory lock so two writers can't fork the chain.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent
from app.models.base import utcnow

GENESIS_HASH = "0" * 64
_LOCK_KEY = 0x4155444954  # "AUDIT"


def _default(value: Any) -> str:
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Not JSON serialisable in audit payload: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default)


def compute_hash(prev_hash: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(body)).encode()).hexdigest()


def _body(event: AuditEvent) -> dict[str, Any]:
    return {
        "occurred_at": event.occurred_at.isoformat(),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_agent": event.actor_agent,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "payload": event.payload,
    }


async def record(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_agent: str | None = None,
) -> AuditEvent:
    """Append an event. The caller commits; the lock is released at commit or rollback."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    last = await session.scalar(select(AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1))
    prev_hash = last or GENESIS_HASH
    event = AuditEvent(
        occurred_at=utcnow(),
        actor_user_id=actor_user_id,
        actor_agent=actor_agent,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        # Round-trip through canonical JSON so what's stored is exactly what was hashed.
        payload=json.loads(canonical_json(payload or {})),
        prev_hash=prev_hash,
    )
    event.hash = compute_hash(prev_hash, _body(event))
    session.add(event)
    await session.flush()
    return event


@dataclass(frozen=True)
class ChainCheck:
    ok: bool
    events_checked: int
    first_bad_seq: int | None = None


async def verify_chain(session: AsyncSession) -> ChainCheck:
    prev = GENESIS_HASH
    count = 0
    result = await session.stream_scalars(select(AuditEvent).order_by(AuditEvent.seq))
    async for event in result:
        count += 1
        if event.prev_hash != prev or compute_hash(prev, _body(event)) != event.hash:
            return ChainCheck(ok=False, events_checked=count, first_bad_seq=event.seq)
        prev = event.hash
    return ChainCheck(ok=True, events_checked=count)
