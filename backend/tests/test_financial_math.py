"""financial_math must stay at 100% coverage (CLAUDE.md). Edge cases first."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.services import financial_math as fm


def test_dscr_basic_and_rounding() -> None:
    assert fm.dscr(D("150"), D("40"), D("60")) == D("1.5000")
    assert fm.dscr(D("100"), D("3"), D("0")) == D("33.3333")  # half-up at 4 dp
    assert fm.dscr(D("2"), D("3"), D("0")) == D("0.6667")


def test_dscr_zero_debt_service_is_undefined() -> None:
    assert fm.dscr(D("100"), D("0"), D("0")) is None


def test_dscr_negative_ebitda_is_reported_not_hidden() -> None:
    assert fm.dscr(D("-50"), D("25"), D("25")) == D("-1.0000")


def test_pro_forma_dscr_adds_new_debt_service() -> None:
    assert fm.pro_forma_dscr(D("150"), D("40"), D("60"), D("50")) == D("1.0000")
    assert fm.pro_forma_dscr(D("150"), D("0"), D("0"), D("0")) is None


@pytest.mark.parametrize(
    ("equity", "expected"),
    [
        (D("50"), D("2.0000")),
        (D("0"), None),
        (D("-10"), None),
    ],
)
def test_debt_to_equity(equity: D, expected: D | None) -> None:
    assert fm.debt_to_equity(D("100"), equity) == expected


@pytest.mark.parametrize(
    ("ebitda", "expected"),
    [
        (D("40"), D("2.5000")),
        (D("0"), None),
        (D("-5"), None),
    ],
)
def test_debt_to_ebitda(ebitda: D, expected: D | None) -> None:
    assert fm.debt_to_ebitda(D("100"), ebitda) == expected


def test_current_ratio() -> None:
    assert fm.current_ratio(D("240"), D("180")) == D("1.3333")
    assert fm.current_ratio(D("240"), D("0")) is None


def test_utilization_pct() -> None:
    assert fm.utilization_pct(D("925"), D("1000")) == D("92.50")
    assert fm.utilization_pct(D("1"), D("3")) == D("33.33")
    assert fm.utilization_pct(D("10"), D("0")) is None


def test_pct_change() -> None:
    assert fm.pct_change(D("100"), D("70")) == D("-30.00")
    assert fm.pct_change(D("100"), D("125")) == D("25.00")
    assert fm.pct_change(D("0"), D("10")) is None


def test_annualise_monthly() -> None:
    assert fm.annualise_monthly([D("10"), D("20")]) == D("180")
    assert fm.annualise_monthly([]) is None


def _weekly(values: list[str], end: date = date(2026, 11, 16)) -> list[tuple[date, D]]:
    n = len(values)
    return [(end - timedelta(weeks=n - 1 - i), D(v)) for i, v in enumerate(values)]


def test_days_continuously_above_counts_the_trailing_run() -> None:
    points = _weekly(["80", "95", "85", "93", "94", "95", "96", "97", "92.5"])
    assert fm.days_continuously_above(points, D("90")) == 35  # last 6 weekly points


def test_days_continuously_above_ignores_input_order() -> None:
    points = _weekly(["91", "92", "93"])
    assert fm.days_continuously_above(list(reversed(points)), D("90")) == 14


def test_days_continuously_above_is_strict_and_zero_when_latest_not_above() -> None:
    assert fm.days_continuously_above(_weekly(["95", "95", "90"]), D("90")) == 0
    assert fm.days_continuously_above([], D("90")) == 0
    assert fm.days_continuously_above(_weekly(["95"]), D("90")) == 0  # a single point spans 0 days


@pytest.mark.parametrize(
    ("value", "op", "expected"),
    [
        (D("1.25"), ">=", True),
        (D("1.2499"), ">=", False),
        (D("1.25"), ">", False),
        (D("1.26"), ">", True),
        (D("3.5"), "<=", True),
        (D("3.5"), "<", False),
        (None, ">=", None),
    ],
)
def test_covenant_passes(value: D | None, op: fm.Operator, expected: bool | None) -> None:
    assert fm.covenant_passes(value, op, D("1.25") if op in (">=", ">") else D("3.5")) is expected


@dataclass
class Snap:
    ebitda: D = D("30")
    interest_expense: D = D("5")
    principal_repayment: D = D("15")
    total_debt: D = D("720")
    total_equity: D = D("400")
    current_assets: D = D("300")
    current_liabilities: D = D("200")


def test_snapshot_ratios_monthly_annualises_ebitda() -> None:
    r = fm.snapshot_ratios(Snap())
    assert r.dscr == D("1.5000")
    assert r.debt_to_equity == D("1.8000")
    assert r.debt_to_ebitda == D("2.0000")  # 720 / (30 * 12)
    assert r.current_ratio == D("1.5000")
    assert r.metric("DSCR") == r.dscr
    assert r.metric("CURRENT_RATIO") == r.current_ratio


def test_snapshot_ratios_annual_period() -> None:
    r = fm.snapshot_ratios(Snap(ebitda=D("360")), months_in_period=12)
    assert r.debt_to_ebitda == D("2.0000")
    assert r.metric("DEBT_TO_EBITDA") == r.debt_to_ebitda
    assert r.metric("DEBT_TO_EQUITY") == r.debt_to_equity


def test_snapshot_ratios_rejects_bad_period() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        fm.snapshot_ratios(Snap(), months_in_period=0)
