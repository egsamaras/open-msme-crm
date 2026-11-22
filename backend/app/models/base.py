import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from sqlalchemy import DateTime, Enum, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Money = Annotated[Decimal, mapped_column(Numeric(18, 2))]
Ratio = Annotated[Decimal, mapped_column(Numeric(10, 4))]
Pct = Annotated[Decimal, mapped_column(Numeric(5, 2))]
Json = Annotated[Any, mapped_column(JSONB)]


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(enum_cls: type[enum.Enum], name: str | None = None) -> Enum:
    """Store enums as VARCHAR + CHECK so adding a value is a plain migration."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
        create_constraint=True,
        name=name or enum_cls.__name__.lower(),
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )
