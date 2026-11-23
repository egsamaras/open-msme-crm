"""Industry benchmarks for credit memos (SPEC 4.2, graph 4).

A small, static, ILLUSTRATIVE table: median ratios for SME borrowers by ISIC section. The numbers
are invented for the demo and are not market data. Replace them with your bank's own peer data.
"""

from dataclasses import dataclass
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class Benchmark:
    industry: str
    dscr_median: Decimal
    debt_to_ebitda_median: Decimal
    current_ratio_median: Decimal


_TABLE = {
    b.industry: b
    for b in [
        Benchmark("Manufacturing", D("1.60"), D("3.0"), D("1.40")),
        Benchmark("Transportation and storage", D("1.45"), D("3.5"), D("1.20")),
        Benchmark("Human health activities", D("1.80"), D("2.5"), D("1.50")),
        Benchmark("Wholesale and retail trade", D("1.50"), D("2.8"), D("1.30")),
        Benchmark("Construction", D("1.35"), D("3.8"), D("1.15")),
        Benchmark("Accommodation and food service", D("1.40"), D("3.2"), D("1.00")),
        Benchmark("Information and communication", D("1.90"), D("2.2"), D("1.60")),
    ]
}
_DEFAULT = Benchmark("All SMEs", D("1.50"), D("3.0"), D("1.30"))

SOURCE = "Illustrative static table (not market data)"


def for_industry(industry: str) -> Benchmark:
    return _TABLE.get(industry, _DEFAULT)
