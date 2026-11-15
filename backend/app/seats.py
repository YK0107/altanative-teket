"""座席定義。フロントと同じ seats.json を読む（Lambda パッケージには同梱する）。"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.pricing import SeatCategory

_CANDIDATES = (
    Path(__file__).with_name("seats.json"),
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "seats.json",
)


@dataclass(frozen=True)
class Seat:
    id: str
    category: SeatCategory
    label: str


def _label(s: dict) -> str:
    if s["c"] == "W":
        return f"1階 車椅子スペース {s['n']}"
    return f"{s['a']} {s['r']}列 {s['n']}番"


@lru_cache
def all_seats() -> dict[str, Seat]:
    path = next(p for p in _CANDIDATES if p.exists())
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["id"]: Seat(s["id"], s["c"], _label(s)) for s in data["seats"]}


def seat_label(seat_id: str) -> str:
    s = all_seats().get(seat_id)
    return s.label if s else seat_id
