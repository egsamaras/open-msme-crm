"""Idempotent synthetic seed data (SPEC 6).

Every row gets a UUID derived from a stable name (or, for history rows, from its date), and rows
are written with `merge`, so running it twice on the same day leaves exactly the same rows. Dates
are relative to the day you run it, so the planted anomalies (for example a licence expiring
within 30 days) stay current; re-running in a later week adds that week's history rows.

All companies and people are invented.

    uv run python -m app.db.seed
"""

import asyncio
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import dispose_engine, get_sessionmaker
from app.models import (
    BeneficialOwner,
    Company,
    Contact,
    Deal,
    Document,
    Facility,
    FacilityUtilization,
    FinancialSnapshot,
    Interaction,
    Task,
    User,
)
from app.models.base import Base
from app.models.enums import (
    ISLAMIC_PRODUCTS,
    DealStage,
    DocumentType,
    InteractionType,
    KybStatus,
    MsmeTier,
    PeriodType,
    Product,
    Role,
    ScreeningStatus,
    TaskSource,
    VerificationStatus,
)

NAMESPACE = uuid.UUID("6f1c3c2e-6d1e-4c38-9a59-3f5f0f6c2a11")
CENT = Decimal("0.01")

# Local currency units per USD (pegged rates, rounded).
FX_PER_USD = {
    "BHD": Decimal("0.376"),
    "SAR": Decimal("3.75"),
    "AED": Decimal("3.6725"),
    "KWD": Decimal("0.307"),
    "OMR": Decimal("0.385"),
    "QAR": Decimal("3.64"),
}
COUNTRY_CCY = {"BH": "BHD", "SA": "SAR", "AE": "AED", "KW": "KWD", "OM": "OMR", "QA": "QAR"}


def sid(*parts: object) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "/".join(str(p) for p in parts))


def money(x: Decimal | float | int) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SeedUser:
    key: str
    email: str
    full_name: str
    role: Role
    branch: str


USERS = [
    SeedUser("rm", "rm@demo.local", "Layla Rahman", Role.RM, "Manama Business Centre"),
    SeedUser("credit", "credit@demo.local", "Omar Faris", Role.CREDIT_OFFICER, "Head Office"),
    SeedUser("compliance", "compliance@demo.local", "Noura Saleh", Role.COMPLIANCE, "Head Office"),
    SeedUser("admin", "admin@demo.local", "Demo Admin", Role.ADMIN, "Head Office"),
]


@dataclass(frozen=True)
class SeedCompany:
    key: str
    legal_name: str
    trading_name: str
    country: str
    industry: str
    turnover_usd: int
    anomaly: str | None = None


COMPANIES = [
    SeedCompany(
        "pearl-bay",
        "Pearl Bay Food Industries W.L.L.",
        "Pearl Bay Foods",
        "BH",
        "Manufacturing",
        6_200_000,
        anomaly="doc_expiry",
    ),
    SeedCompany(
        "dunes-logistics",
        "Dunes Freight & Logistics Co.",
        "Dunes Freight",
        "SA",
        "Transportation and storage",
        11_500_000,
        anomaly="cashflow_drop",
    ),
    SeedCompany(
        "falcon-steel",
        "Falcon Light Steel Fabrication LLC",
        "Falcon Steel",
        "AE",
        "Manufacturing",
        8_400_000,
        anomaly="utilization_spike",
    ),
    SeedCompany(
        "oasis-clinics",
        "Oasis Family Clinics W.L.L.",
        "Oasis Clinics",
        "BH",
        "Human health activities",
        2_100_000,
        anomaly="bounced_cheques",
    ),
    SeedCompany(
        "gulf-spice",
        "Gulf Spice Trading Company",
        "Gulf Spice",
        "KW",
        "Wholesale and retail trade",
        3_900_000,
        anomaly="ubo_mismatch",
    ),
    SeedCompany(
        "sadaf-build",
        "Sadaf Building Contracting LLC",
        "Sadaf Build",
        "OM",
        "Construction",
        14_200_000,
    ),
    SeedCompany(
        "nakheel-dates",
        "Nakheel Premium Dates Co.",
        "Nakheel Dates",
        "SA",
        "Manufacturing",
        4_700_000,
    ),
    SeedCompany(
        "marina-cafe",
        "Marina Cafe Group W.L.L.",
        "Marina Cafe",
        "QA",
        "Accommodation and food service",
        1_300_000,
    ),
    SeedCompany(
        "azure-pack",
        "Azure Packaging Solutions LLC",
        "Azure Pack",
        "AE",
        "Manufacturing",
        5_600_000,
    ),
    SeedCompany(
        "riffa-medical",
        "Riffa Medical Supplies W.L.L.",
        "Riffa Medical",
        "BH",
        "Wholesale and retail trade",
        950_000,
    ),
    SeedCompany(
        "caravan-cold",
        "Caravan Cold Chain Co.",
        "Caravan Cold Chain",
        "KW",
        "Transportation and storage",
        7_300_000,
    ),
    SeedCompany(
        "lulu-bakers",
        "Golden Crescent Bakeries LLC",
        "Golden Crescent",
        "OM",
        "Accommodation and food service",
        640_000,
    ),
    SeedCompany(
        "horizon-dental",
        "Horizon Dental Centre W.L.L.",
        "Horizon Dental",
        "QA",
        "Human health activities",
        1_800_000,
    ),
    SeedCompany(
        "souq-electro",
        "Souq Electrical Wholesale Co.",
        "Souq Electrical",
        "SA",
        "Wholesale and retail trade",
        9_800_000,
    ),
    SeedCompany(
        "tide-print",
        "Tide Print & Media W.L.L.",
        "Tide Print",
        "BH",
        "Information and communication",
        280_000,
    ),
]

OWNER_NAMES = [
    "Khalid Mansour",
    "Fatima Al Aswad",
    "Yousef Darwish",
    "Mariam Qasim",
    "Hassan Jaber",
    "Aisha Nasser",
    "Saeed Karim",
    "Huda Mahmoud",
    "Tariq Hamdan",
    "Salma Idris",
    "Rashid Bakr",
    "Dana Yaqoob",
]
CONTACT_TITLES = ["Finance Manager", "Managing Director", "Chief Accountant", "Operations Head"]
DEAL_STAGES = [
    DealStage.LEAD,
    DealStage.QUALIFICATION,
    DealStage.DOC_COLLECTION,
    DealStage.CREDIT_UNDERWRITING,
    DealStage.CREDIT_UNDERWRITING,
    DealStage.APPROVAL,
    DealStage.DISBURSED,
    DealStage.LOST,
]
STAGE_PROBABILITY = {
    DealStage.LEAD: 10,
    DealStage.QUALIFICATION: 25,
    DealStage.DOC_COLLECTION: 40,
    DealStage.CREDIT_UNDERWRITING: 60,
    DealStage.APPROVAL: 80,
    DealStage.DISBURSED: 100,
    DealStage.LOST: 0,
}


def tier_for(turnover_usd: int) -> MsmeTier:
    if turnover_usd < 1_000_000:
        return MsmeTier.MICRO
    if turnover_usd < 5_000_000:
        return MsmeTier.SMALL
    return MsmeTier.MEDIUM


def month_ends(today: date, n: int) -> list[date]:
    """The last n month-ends before today, oldest first."""
    ends: list[date] = []
    d = today.replace(day=1) - timedelta(days=1)
    for _ in range(n):
        ends.append(d)
        d = d.replace(day=1) - timedelta(days=1)
    return list(reversed(ends))


def build(today: date, password_hash: str) -> list[Base]:
    rows: list[Base] = []
    users = {
        u.key: User(
            id=sid("user", u.key),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            branch=u.branch,
            password_hash=password_hash,
            is_active=True,
        )
        for u in USERS
    }
    rows.extend(users.values())
    rm = users["rm"]

    for idx, c in enumerate(COMPANIES):
        rng = random.Random(c.key)  # stable per company
        ccy = COUNTRY_CCY[c.country]
        fx = FX_PER_USD[ccy]
        turnover = money(c.turnover_usd * fx)
        cid = sid("company", c.key)
        kyb_status = KybStatus.PENDING_RENEWAL if c.anomaly == "doc_expiry" else KybStatus.VERIFIED
        rows.append(
            Company(
                id=cid,
                legal_name=c.legal_name,
                trading_name=c.trading_name,
                cr_number=f"{c.country}-{100000 + idx * 7919}",
                country=c.country,
                industry=c.industry,
                tier=tier_for(c.turnover_usd),
                annual_turnover=turnover,
                currency=ccy,
                risk_rating=rng.randint(3, 6) + (2 if c.anomaly else 0),
                kyb_status=kyb_status,
                kyb_next_review=today + timedelta(days=rng.randint(60, 300)),
                rm_id=rm.id,
            )
        )

        # Owners: two or three, summing to 100%.
        names = rng.sample(OWNER_NAMES, 3)
        splits = (
            [Decimal("60"), Decimal("40")]
            if idx % 2
            else [Decimal("45"), Decimal("30"), Decimal("25")]
        )
        for i, pct in enumerate(splits):
            rows.append(
                BeneficialOwner(
                    id=sid("owner", c.key, i),
                    company_id=cid,
                    full_name=names[i],
                    nationality=c.country,
                    ownership_pct=pct,
                    pep_status=ScreeningStatus.CLEAR,
                    sanctions_status=ScreeningStatus.CLEAR,
                )
            )

        for i in range(2):
            name = rng.choice(OWNER_NAMES)
            rows.append(
                Contact(
                    id=sid("contact", c.key, i),
                    company_id=cid,
                    full_name=name,
                    title=CONTACT_TITLES[(idx + i) % len(CONTACT_TITLES)],
                    email=f"{name.split()[0].lower()}@{c.key}.example",
                    phone=f"+000 5{idx:02d}{i} 0000",
                    is_primary=i == 0,
                )
            )

        # Facilities: working capital for everyone, plus one more product.
        monthly_rev = turnover / 12
        wc_product = Product.MURABAHA if idx % 3 == 0 else Product.WORKING_CAPITAL
        second = [
            Product.TERM_LOAN,
            Product.TRADE_FINANCE_LC,
            Product.IJARA,
            Product.LETTER_OF_GUARANTEE,
            Product.FX_LINE,
        ][idx % 5]
        facilities: list[tuple[str, Product, Decimal]] = [
            ("wc", wc_product, money(monthly_rev * Decimal("1.5"))),
            ("second", second, money(monthly_rev * Decimal("2.5"))),
        ]
        for fkey, product, limit in facilities:
            fid = sid("facility", c.key, fkey)
            covenants = (
                [{"metric": "DSCR", "operator": ">=", "threshold": "1.25"}]
                if product in (Product.TERM_LOAN, Product.IJARA)
                else []
            )
            base_util = Decimal(str(rng.uniform(0.45, 0.75)))
            week_start = today - timedelta(days=today.weekday())  # Monday, stable all week
            points: list[tuple[date, Decimal]] = []
            for w in range(26):
                drift = Decimal(str(rng.uniform(-0.05, 0.05)))
                ratio = min(max(base_util + drift, Decimal("0.05")), Decimal("0.88"))
                if c.anomaly == "utilization_spike" and fkey == "wc" and w >= 20:
                    ratio = Decimal(str(rng.uniform(0.925, 0.97)))  # last 6 weeks above 92%
                points.append((week_start - timedelta(weeks=25 - w), money(limit * ratio)))
            # Parent first: merge() autoflushes, so children must not precede their parent.
            rows.append(
                Facility(
                    id=fid,
                    company_id=cid,
                    product=product,
                    is_islamic=product in ISLAMIC_PRODUCTS,
                    sanctioned_limit=limit,
                    utilized_amount=points[-1][1],
                    rate_pct=Decimal(str(round(rng.uniform(5.5, 8.5), 2))),
                    start_date=today - timedelta(days=rng.randint(200, 900)),
                    maturity_date=today + timedelta(days=rng.randint(120, 1400)),
                    covenants=covenants,
                )
            )
            rows.extend(
                FacilityUtilization(
                    id=sid("util", fid, as_of), facility_id=fid, as_of=as_of, utilized_amount=used
                )
                for as_of, used in points
            )

        # Six monthly snapshots of raw inputs.
        total_debt = money(sum(lim for _, _, lim in facilities) * Decimal("0.6"))
        balances: list[Decimal] = []
        for m, period_end in enumerate(month_ends(today, 6)):
            season = Decimal(str(1 + 0.08 * ((m % 3) - 1)))
            revenue = money(monthly_rev * season * Decimal(str(rng.uniform(0.95, 1.05))))
            ebitda = money(revenue * Decimal(str(rng.uniform(0.12, 0.18))))
            interest = money(total_debt * Decimal("0.07") / 12)
            principal = money(total_debt / 48)
            balance = money(revenue * Decimal(str(rng.uniform(0.32, 0.38))))
            if c.anomaly == "cashflow_drop" and m >= 4:
                # Anchor to month 3 so seasonality can't dilute it: -20%, then -38% (> 25% rule).
                balance = money(balances[3] * (Decimal("0.80") if m == 4 else Decimal("0.62")))
            balances.append(balance)
            bounced = 3 if c.anomaly == "bounced_cheques" and m == 5 else 0
            rows.append(
                FinancialSnapshot(
                    id=sid("snapshot", c.key, period_end),
                    company_id=cid,
                    period_end=period_end,
                    period_type=PeriodType.MONTHLY,
                    revenue=revenue,
                    ebitda=ebitda,
                    net_profit=money((ebitda - interest) * Decimal("0.85")),
                    interest_expense=interest,
                    principal_repayment=principal,
                    total_debt=total_debt,
                    total_equity=money(turnover * Decimal("0.35")),
                    current_assets=money(revenue * Decimal("2.4")),
                    current_liabilities=money(revenue * Decimal("1.8")),
                    avg_bank_balance=balance,
                    bounced_cheques=bounced,
                )
            )

        # Documents.
        licence_expiry = today + timedelta(
            days=18 if c.anomaly == "doc_expiry" else rng.randint(120, 600)
        )
        rows.append(
            Document(
                id=sid("doc", c.key, "licence"),
                company_id=cid,
                doc_type=DocumentType.TRADE_LICENSE,
                file_name=f"{c.key}-trade-licence.pdf",
                expiry_date=licence_expiry,
                verification_status=VerificationStatus.VERIFIED,
                extracted_fields={},
            )
        )
        rows.append(
            Document(
                id=sid("doc", c.key, "cr"),
                company_id=cid,
                doc_type=DocumentType.CR_CERTIFICATE,
                file_name=f"{c.key}-cr-certificate.pdf",
                expiry_date=today + timedelta(days=rng.randint(200, 700)),
                verification_status=VerificationStatus.VERIFIED,
                extracted_fields={},
            )
        )
        declared = list(zip(names, splits, strict=False))
        if c.anomaly == "ubo_mismatch":
            # The declaration disagrees with the database: owner 2 now holds 35%, owner 3 15%.
            declared = [
                (names[0], Decimal("50")),
                (names[1], Decimal("35")),
                (names[2], Decimal("15")),
            ]
        rows.append(
            Document(
                id=sid("doc", c.key, "ubo"),
                company_id=cid,
                doc_type=DocumentType.UBO_DECLARATION,
                file_name=f"{c.key}-ubo-declaration.txt",
                content_text="UBO DECLARATION\n" + "\n".join(f"{n}: {p}%" for n, p in declared),
                verification_status=(
                    VerificationStatus.PENDING
                    if c.anomaly == "ubo_mismatch"
                    else VerificationStatus.VERIFIED
                ),
                extracted_fields={},
            )
        )

        # Interactions.
        for i in range(3):
            when = datetime.combine(
                today - timedelta(days=12 + i * 27 + idx), time(10, 0), tzinfo=UTC
            )
            itype = [InteractionType.MEETING, InteractionType.CALL, InteractionType.SITE_VISIT][i]
            rows.append(
                Interaction(
                    id=sid("interaction", c.key, i),
                    company_id=cid,
                    user_id=rm.id,
                    interaction_type=itype,
                    occurred_at=when,
                    summary=f"{itype.value.replace('_', ' ').title()} with {c.trading_name}",
                    notes="Synthetic note for demo purposes.",
                )
            )

        # Deals for most companies.
        if idx < len(DEAL_STAGES) + 4:
            stage = DEAL_STAGES[idx % len(DEAL_STAGES)]
            product = [
                Product.TERM_LOAN,
                Product.MURABAHA,
                Product.TRADE_FINANCE_LC,
                Product.WORKING_CAPITAL,
            ][idx % 4]
            rows.append(
                Deal(
                    id=sid("deal", c.key),
                    company_id=cid,
                    title=f"{c.trading_name} — {product.value.replace('_', ' ').title()}",
                    product=product,
                    stage=stage,
                    requested_amount=money(monthly_rev * Decimal(str(rng.choice([1, 2, 3])))),
                    probability_pct=STAGE_PROBABILITY[stage],
                    expected_close=today + timedelta(days=rng.randint(10, 120)),
                    owner_id=rm.id,
                )
            )

        rows.append(
            Task(
                id=sid("task", c.key),
                company_id=cid,
                assignee_id=rm.id,
                title=f"Quarterly review call: {c.trading_name}",
                due_date=today + timedelta(days=rng.randint(3, 40)),
                source=TaskSource.MANUAL,
            )
        )

    return rows


async def seed(session: AsyncSession, today: date | None = None) -> int:
    rows = build(today or datetime.now(UTC).date(), hash_password(get_settings().seed_password))
    for row in rows:
        await session.merge(row)
    await session.commit()
    return len(rows)


async def main() -> None:
    async with get_sessionmaker()() as session:
        n = await seed(session)
    await dispose_engine()
    print(f"Seeded {n} rows (idempotent).")


if __name__ == "__main__":
    asyncio.run(main())
