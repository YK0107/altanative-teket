"""料金計算。フロント(frontend/src/lib/seats.ts の calcTotal)と同じ規則。"""

from dataclasses import dataclass
from typing import Literal

SeatCategory = Literal["S", "A", "W"]

PRICES: dict[SeatCategory, int] = {"S": 1000, "A": 500, "W": 500}
COUPON_DISCOUNT = 500


@dataclass(frozen=True)
class Line:
    seat_id: str
    category: SeatCategory
    price: int
    discount: int

    @property
    def subtotal(self) -> int:
        return self.price - self.discount


def calc_total(
    seats: list[tuple[str, SeatCategory]],
    coupon_count: int,
    prices: dict[SeatCategory, int] = PRICES,
    coupon_discount: int = COUPON_DISCOUNT,
) -> tuple[list[Line], int]:
    """クーポンは1枚あたり定額引き。高い席から適用し、0円未満にはしない。"""
    ordered = sorted(seats, key=lambda s: prices[s[1]], reverse=True)
    lines = []
    for i, (seat_id, cat) in enumerate(ordered):
        price = prices[cat]
        discount = min(coupon_discount, price) if i < coupon_count else 0
        lines.append(Line(seat_id, cat, price, discount))
    return lines, sum(line.subtotal for line in lines)
