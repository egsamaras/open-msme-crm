"""Deterministic financial calculations (SPEC 4.1, rule 3).

Pure functions on `Decimal`. No I/O, no floats, no LLM. Every number an agent narrates comes from
here. Functions return `None` when a ratio is undefined (for example a zero denominator) rather
than inventing a value, and callers must show that as "not available".

Ratios are rounded to 4 decimal places, percentages to 2, half-up.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

RATIO_Q = Decimal("0.0001")
PCT_Q = Decimal("0.01")
ZERO = Decimal(0)
HUNDRED = Decimal(100)

Operator = Literal[">=", ">", "<=", "<"]
Metric = Literal["DSCR", "DEBT_TO_EQUITY", "DEBT_TO_EBITDA", "CURRENT_RATIO"]


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == ZERO:
        return None
    return (numerator / denominator).quantize(RATIO_Q, rounding=ROUND_HALF_UP)


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == ZERO:
        return None
    return (numerator / denominator * HUNDRED).quantize(PCT_Q, rounding=ROUND_HALF_UP)


def debt_service(interest: Decimal, principal: Decimal) -> Decimal:
    return interest + principal


def dscr(ebitda: Decimal, interest: Decimal, principal: Decimal) -> Decimal | None:
    """Debt service coverage: EBITDA / (interest + principal). None with no debt service."""
    return _ratio(ebitda, debt_service(interest, principal))


def pro_forma_dscr(
    ebitda: Decimal, interest: Decimal, principal: Decimal, new_debt_service: Decimal
) -> Decimal | None:
    """DSCR if a new facility's debt service (same period) is added to the existing one."""
    return _ratio(ebitda, debt_service(interest, principal) + new_debt_service)


def debt_to_equity(total_debt: Decimal, total_equity: Decimal) -> Decimal | None:
    """Leverage. None when equity is zero or negative, where the ratio is meaningless."""
    if total_equity <= ZERO:
        return None
    return _ratio(total_debt, total_equity)


def debt_to_ebitda(total_debt: Decimal, annual_ebitda: Decimal) -> Decimal | None:
    """None when EBITDA is zero or negative (the business can't service debt from earnings)."""
    if annual_ebitda <= ZERO:
        return None
    return _ratio(total_debt, annual_ebitda)


def current_ratio(current_assets: Decimal, current_liabilities: Decimal) -> Decimal | None:
    return _ratio(current_assets, current_liabilities)


def utilization_pct(utilized: Decimal, limit: Decimal) -> Decimal | None:
    return _pct(utilized, limit)


def pct_change(old: Decimal, new: Decimal) -> Decimal | None:
    """Percentage change from old to new; negative is a fall. None when old is zero."""
    return _pct(new - old, old)


def annualise_monthly(values: Sequence[Decimal]) -> Decimal | None:
    """Average of monthly values times 12. None for an empty series."""
    if not values:
        return None
    return sum(values, ZERO) / len(values) * 12


def days_continuously_above(points: Sequence[tuple[date, Decimal]], threshold: Decimal) -> int:
    """Length in days of the run of points strictly above `threshold` that ends at the latest point.

    Points are (date, value) pairs in any order. Returns 0 if the latest point is not above the
    threshold. With weekly points, six consecutive weeks above the line give 35 days.
    """
    ordered = sorted(points)
    if not ordered or ordered[-1][1] <= threshold:
        return 0
    start = ordered[-1][0]
    for as_of, value in reversed(ordered):
        if value <= threshold:
            break
        start = as_of
    return (ordered[-1][0] - start).days


def covenant_passes(value: Decimal | None, operator: Operator, threshold: Decimal) -> bool | None:
    """Test a covenant. None when the metric itself is undefined, so it can't be tested."""
    if value is None:
        return None
    match operator:
        case ">=":
            return value >= threshold
        case ">":
            return value > threshold
        case "<=":
            return value <= threshold
        case "<":
            return value < threshold


class SnapshotInputs(Protocol):
    """The raw inputs of a FinancialSnapshot (the ORM model satisfies this)."""

    @property
    def ebitda(self) -> Decimal: ...
    @property
    def interest_expense(self) -> Decimal: ...
    @property
    def principal_repayment(self) -> Decimal: ...
    @property
    def total_debt(self) -> Decimal: ...
    @property
    def total_equity(self) -> Decimal: ...
    @property
    def current_assets(self) -> Decimal: ...
    @property
    def current_liabilities(self) -> Decimal: ...


@dataclass(frozen=True)
class SnapshotRatios:
    dscr: Decimal | None
    debt_to_equity: Decimal | None
    debt_to_ebitda: Decimal | None
    current_ratio: Decimal | None

    def metric(self, name: Metric) -> Decimal | None:
        return {
            "DSCR": self.dscr,
            "DEBT_TO_EQUITY": self.debt_to_equity,
            "DEBT_TO_EBITDA": self.debt_to_ebitda,
            "CURRENT_RATIO": self.current_ratio,
        }[name]


def snapshot_ratios(s: SnapshotInputs, *, months_in_period: int = 1) -> SnapshotRatios:
    """Ratios for one snapshot. `months_in_period` annualises EBITDA (1 = monthly, 12 = annual)."""
    if months_in_period < 1:
        raise ValueError("months_in_period must be at least 1")
    annual_ebitda = s.ebitda * 12 / months_in_period
    return SnapshotRatios(
        dscr=dscr(s.ebitda, s.interest_expense, s.principal_repayment),
        debt_to_equity=debt_to_equity(s.total_debt, s.total_equity),
        debt_to_ebitda=debt_to_ebitda(s.total_debt, annual_ebitda),
        current_ratio=current_ratio(s.current_assets, s.current_liabilities),
    )


def monthly_debt_service(amount: Decimal, rate_pct: Decimal, tenor_months: int | None) -> Decimal:
    """Monthly debt service of a new facility: straight-line principal plus monthly interest.

    `tenor_months=None` means a revolving line serviced interest-only. Deliberately simple and
    conservative for pro-forma DSCR (interest on the full amount every month). 2 decimal places.
    """
    if tenor_months is not None and tenor_months < 1:
        raise ValueError("tenor_months must be at least 1")
    interest = amount * rate_pct / HUNDRED / 12
    principal = amount / tenor_months if tenor_months else ZERO
    return (principal + interest).quantize(PCT_Q, rounding=ROUND_HALF_UP)


def spread_pct(values: Sequence[Decimal]) -> Decimal | None:
    """(max - min) / max as a percentage: how far a series dips below its peak. None if empty."""
    if not values:
        return None
    peak = max(values)
    if peak <= ZERO:
        return None
    return _pct(peak - min(values), peak)


def _band(
    value: Decimal | None, bands: Sequence[tuple[Decimal, int]], worst: int, *, high_is_good: bool
) -> int:
    if value is None:
        return worst
    for limit, points in bands:
        if (value >= limit) if high_is_good else (value <= limit):
            return points
    return worst


def indicative_risk_grade(
    dscr_value: Decimal | None,
    debt_to_ebitda_value: Decimal | None,
    current_ratio_value: Decimal | None,
) -> int:
    """A transparent scorecard grade from 1 (strongest) to 10 (weakest).

    Indicative only: it orders cases for a credit officer and never decides anything. A ratio that
    can't be computed scores as weak, because missing evidence is not comfort.
    """
    points = _band(
        dscr_value,
        [(Decimal("2.0"), 0), (Decimal("1.5"), 1), (Decimal("1.25"), 2), (Decimal("1.0"), 3)],
        4,
        high_is_good=True,
    )
    points += _band(
        debt_to_ebitda_value,
        [(Decimal("2"), 0), (Decimal("3"), 1), (Decimal("4"), 2), (Decimal("5"), 3)],
        4,
        high_is_good=False,
    )
    points += _band(
        current_ratio_value,
        [(Decimal("1.5"), 0), (Decimal("1.2"), 1), (Decimal("1.0"), 2)],
        3,
        high_is_good=True,
    )
    return 1 + (points * 9 + 5) // 11
