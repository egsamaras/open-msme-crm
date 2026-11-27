"""KYB document intake rules (SPEC 4.2, graph 2). Deterministic and pure.

Uploaded text is untrusted. It only ever reaches the LLM as data to extract from, and whatever the
LLM extracts passes `validate` (schema and range checks) and `reconcile` (comparison with the
database) before anything can change, and any change still needs a compliance officer's approval.
"""

import io
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import DocumentType
from app.services import financial_math as fm

MAX_UPLOAD_BYTES = 1_000_000
MAX_TEXT_CHARS = 20_000
ALLOWED_SUFFIXES = (".txt", ".json", ".pdf")
EXPIRING_DOC_TYPES = frozenset({DocumentType.TRADE_LICENSE, DocumentType.CR_CERTIFICATE})
FINANCIAL_TOLERANCE_PCT = Decimal(10)
OWNERSHIP_TOLERANCE_PCT = Decimal("0.5")


class ExtractedOwner(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    ownership_pct: Decimal


class ExtractedFields(BaseModel):
    """What the extraction step may return. Every field is optional: absent means not found."""

    cr_number: str | None = Field(default=None, max_length=64)
    legal_name: str | None = Field(default=None, max_length=255)
    expiry_date: date | None = None
    period_end: date | None = None
    revenue: Decimal | None = None
    ebitda: Decimal | None = None
    owners: list[ExtractedOwner] = Field(default_factory=list, max_length=20)


@dataclass
class Reconciliation:
    discrepancies: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    owner_changes_only: bool = False
    proposed_owners: list[dict[str, str]] = field(default_factory=list)


def text_from_upload(file_name: str, data: bytes) -> str:
    """Plain text from a .txt, .json or .pdf upload. Raises ValueError for anything else."""
    name = file_name.lower()
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"File is larger than {MAX_UPLOAD_BYTES // 1000} KB")
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:  # pypdf raises many types for malformed files
            raise ValueError("Couldn't read that PDF") from e
    elif name.endswith((".txt", ".json")):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError("Text files must be UTF-8") from e
        if name.endswith(".json"):
            try:
                json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError("That isn't valid JSON") from e
    else:
        raise ValueError("Upload a .txt, .json or .pdf file")
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("The file has no readable text")
    return text[:MAX_TEXT_CHARS]


def validate(fields: ExtractedFields, today: date) -> list[str]:
    """Range checks on extracted values. Returns problems; empty means plausible."""
    problems = []
    total = Decimal(0)
    for o in fields.owners:
        if not Decimal(0) < o.ownership_pct <= Decimal(100):
            problems.append(f"{o.full_name}: ownership {o.ownership_pct}% is out of range")
        total += o.ownership_pct
    if total > Decimal(100) + OWNERSHIP_TOLERANCE_PCT:
        problems.append(f"declared ownership adds up to {total}%, more than 100%")
    if len({o.full_name.casefold() for o in fields.owners}) != len(fields.owners):
        problems.append("an owner is listed twice")
    for label, d in (("expiry date", fields.expiry_date), ("period end", fields.period_end)):
        if d is not None and not date(2000, 1, 1) <= d <= date(2100, 1, 1):
            problems.append(f"{label} {d} is implausible")
    if fields.period_end is not None and fields.period_end > today:
        problems.append(f"period end {fields.period_end} is in the future")
    for label, v in (("revenue", fields.revenue), ("EBITDA", fields.ebitda)):
        if v is not None and abs(v) > Decimal("1e12"):
            problems.append(f"{label} {v} is implausible")
    if fields.revenue is not None and fields.revenue < 0:
        problems.append("revenue is negative")
    return problems


def _years_after(day: date, years: int) -> date:
    """`day` that many years later; 29 February becomes 28 February in a common year."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def reconcile(
    *,
    doc_type: DocumentType,
    fields: ExtractedFields,
    problems: list[str],
    company: dict[str, Any],
    owners: list[dict[str, Any]],
    annual_revenue: Decimal | None,
    annual_ebitda: Decimal | None,
    ubo_threshold: Decimal,
    today: date,
    expiry_warning_days: int = 30,
    max_validity_years: int = 5,
) -> Reconciliation:
    """Compare a document's extracted fields with what the bank holds."""
    r = Reconciliation()
    r.discrepancies += [{"kind": "invalid", "detail": p} for p in problems]

    if fields.cr_number and fields.cr_number.strip() != company["cr_number"]:
        r.discrepancies.append(
            {
                "kind": "cr_mismatch",
                "detail": f"document says CR {fields.cr_number}, "
                f"the bank has {company['cr_number']}",
            }
        )

    if doc_type in EXPIRING_DOC_TYPES:
        # If verified, an undated licence or certificate never takes over from the one in force,
        # and one dated implausibly far ahead takes over and silences its expiry alert, so both
        # go to a person.
        expiry = fields.expiry_date
        if expiry is None:
            r.discrepancies.append(
                {"kind": "missing_expiry", "detail": "no expiry date could be read"}
            )
        elif expiry > _years_after(today, max_validity_years):
            r.discrepancies.append(
                {
                    "kind": "implausible_expiry",
                    "detail": f"expires on {expiry.isoformat()}, more than "
                    f"{max_validity_years} year{'' if max_validity_years == 1 else 's'} from now",
                }
            )
        else:
            days = (expiry - today).days
            if days < 0:
                r.discrepancies.append(
                    {"kind": "expired", "detail": f"expired on {expiry.isoformat()}"}
                )
            elif days <= expiry_warning_days:
                r.notes.append(f"valid, but expires in {days} days ({expiry.isoformat()})")

    if doc_type == DocumentType.UBO_DECLARATION and fields.owners and not problems:
        held = {o["full_name"].casefold(): o for o in owners}
        declared = {o.full_name.casefold(): o for o in fields.owners}
        owner_diffs = []
        for key, o in declared.items():
            row = held.get(key)
            if row is None:
                owner_diffs.append(f"{o.full_name} ({o.ownership_pct}%) is not on the register")
            elif abs(Decimal(row["ownership_pct"]) - o.ownership_pct) > OWNERSHIP_TOLERANCE_PCT:
                was, now = Decimal(row["ownership_pct"]), o.ownership_pct
                crossing = (was >= ubo_threshold) != (now >= ubo_threshold)
                owner_diffs.append(
                    f"{row['full_name']}: register {was}%, declaration {now}%"
                    + (" (crosses the UBO threshold)" if crossing else "")
                )
        for key, row in held.items():
            if key not in declared:
                owner_diffs.append(f"{row['full_name']} is on the register but not declared")
        r.discrepancies += [{"kind": "owner_change", "detail": d} for d in owner_diffs]
        r.proposed_owners = [
            {"full_name": o.full_name, "ownership_pct": str(o.ownership_pct)} for o in fields.owners
        ]

    if doc_type == DocumentType.FINANCIAL_STATEMENT:
        for label, stated, held_value in (
            ("revenue", fields.revenue, annual_revenue),
            ("EBITDA", fields.ebitda, annual_ebitda),
        ):
            if stated is None or held_value is None:
                continue
            diff = fm.pct_change(held_value, stated)
            if diff is not None and abs(diff) > FINANCIAL_TOLERANCE_PCT:
                r.discrepancies.append(
                    {
                        "kind": "financial_mismatch",
                        "detail": f"stated {label} {stated} vs {held_value.quantize(Decimal('1'))} "
                        f"annualised from the bank's monthly figures ({diff}%)",
                    }
                )

    r.owner_changes_only = bool(r.discrepancies) and all(
        d["kind"] == "owner_change" for d in r.discrepancies
    )
    return r
