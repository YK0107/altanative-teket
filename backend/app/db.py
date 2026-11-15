"""DynamoDB シングルテーブルのキーとアクセス補助。

| 項目     | pk                 | sk            | 備考                                        |
|----------|--------------------|---------------|---------------------------------------------|
| 公演     | EVENT#{event_id}   | META          | 価格・販売期間など                          |
| 座席     | EVENT#{event_id}   | SEAT#{seat}   | status=AVAILABLE/HELD/SOLD                  |
| 注文     | ORDER#{order_id}   | META          | gsi1: 公演別の注文一覧                      |
| チケット | TICKET#{token}     | META          |                                             |
| Stripe   | SESSION#{sid}      | META          | Checkout Session → 注文                     |
| クーポン | COUPON#{code}      | META          |                                             |

gsi2 は疎インデックス。売れた/仮押さえ中の座席（SEATS#）、決済待ちの注文（PENDING#）、
メール未送信の注文（EMAIL#）だけが載る。
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def event_pk(event_id: str) -> str:
    return f"EVENT#{event_id}"


def seat_key(event_id: str, seat_id: str) -> dict[str, str]:
    return {"pk": event_pk(event_id), "sk": f"SEAT#{seat_id}"}


def order_key(order_id: str) -> dict[str, str]:
    return {"pk": f"ORDER#{order_id}", "sk": "META"}


def ticket_key(token: str) -> dict[str, str]:
    return {"pk": f"TICKET#{token}", "sk": "META"}


def session_key(session_id: str) -> dict[str, str]:
    return {"pk": f"SESSION#{session_id}", "sk": "META"}


def coupon_key(code: str) -> dict[str, str]:
    return {"pk": f"COUPON#{code}", "sk": "META"}


def plain(v: Any) -> Any:
    """Decimal を int に戻す（金額・枚数はすべて整数）。"""
    if isinstance(v, Decimal):
        return int(v)
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    return v


@dataclass
class TransactionCanceled(Exception):
    """TransactWriteItems の失敗。reasons は各項目の失敗理由コード（成功項目は "None"）。"""

    reasons: list[str]

    def failed(self) -> list[int]:
        return [i for i, r in enumerate(self.reasons) if r not in ("None", "")]


class Db:
    def __init__(self, table_name: str, resource: Any = None):
        self.resource = resource or boto3.resource("dynamodb")
        self.table = self.resource.Table(table_name)
        self.client = self.resource.meta.client

    def get(self, key: dict[str, str], consistent: bool = True) -> dict | None:
        item = self.table.get_item(Key=key, ConsistentRead=consistent).get("Item")
        return plain(item) if item else None

    def query_all(self, **kwargs: Any) -> list[dict]:
        items: list[dict] = []
        while True:
            res = self.table.query(**kwargs)
            items.extend(plain(i) for i in res.get("Items", []))
            if "LastEvaluatedKey" not in res:
                return items
            kwargs["ExclusiveStartKey"] = res["LastEvaluatedKey"]

    def transact(self, items: list[dict]) -> None:
        table = self.table.name
        for it in items:
            next(iter(it.values()))["TableName"] = table
        try:
            self.client.transact_write_items(TransactItems=items)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "TransactionCanceledException":
                raise
            reasons = [r.get("Code", "None") for r in e.response.get("CancellationReasons", [])]
            raise TransactionCanceled(reasons or ["Unknown"] * len(items)) from e


@lru_cache
def get_db() -> Db:
    return Db(get_settings().table_name)
