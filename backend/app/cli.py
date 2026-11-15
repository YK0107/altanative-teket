"""運用コマンド。

    uv run python -m app.cli seed-event backend/event.json      # 公演情報の登録・更新（価格変更もこれ）
    uv run python -m app.cli seed-seats                         # 座席の初期登録（既存の座席は変更しない）
    uv run python -m app.cli import-coupons coupons.txt         # クーポンコード（1行1個）
    uv run python -m app.cli hash-password                      # 管理者パスワードのハッシュを生成

TABLE_NAME / EVENT_ID は環境変数で指定する。
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

from botocore.exceptions import ClientError

from app import db
from app.auth import hash_password
from app.config import get_settings
from app.seats import all_seats
from app.service import normalize_coupon

EVENT_FIELDS = (
    "name",
    "starts_at",
    "doors_open_at",
    "venue",
    "sales_start",
    "sales_end",
    "published",
    "prices",
    "coupon_discount",
    "max_per_order",
)


def seed_event(d: db.Db, event_id: str, path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in EVENT_FIELDS if k not in data]
    if missing:
        sys.exit(f"missing fields: {missing}")
    if set(data["prices"]) != {"S", "A", "W"} or not all(isinstance(v, int) and v > 0 for v in data["prices"].values()):
        sys.exit("prices must be positive integers for S, A, W")
    d.table.put_item(Item={"pk": db.event_pk(event_id), "sk": "META", **{k: data[k] for k in EVENT_FIELDS}})
    print(f"event {event_id} saved")


def seed_seats(d: db.Db, event_id: str) -> None:
    """未登録の座席だけを AVAILABLE で作る。既存の座席（販売済みなど）には触れない。"""
    existing = {
        i["seat_id"]
        for i in d.query_all(
            KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
            ExpressionAttributeValues={":p": db.event_pk(event_id), ":s": "SEAT#"},
            ProjectionExpression="seat_id",
        )
    }
    missing = [sid for sid in all_seats() if sid not in existing]
    if not existing:
        # 初回登録（座席がまだ1つもない＝販売前）は一括書き込み
        with d.table.batch_writer() as w:
            for sid in missing:
                w.put_item(Item={**db.seat_key(event_id, sid), "seat_id": sid, "status": "AVAILABLE"})
        missing_conditional: list[str] = []
    else:
        missing_conditional = missing
    for sid in missing_conditional:
        # 販売開始前に実行する前提だが、念のため条件付きで作成（同時に予約された座席を上書きしない）
        try:
            d.table.put_item(
                Item={**db.seat_key(event_id, sid), "seat_id": sid, "status": "AVAILABLE"},
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    print(f"seats created: {len(missing)} / {len(all_seats())}")


def import_coupons(d: db.Db, path: Path) -> None:
    codes = {c for line in path.read_text(encoding="utf-8").splitlines() if (c := normalize_coupon(line))}
    with d.table.batch_writer() as w:
        for c in sorted(codes):
            w.put_item(Item={**db.coupon_key(c), "code": c})
    print(f"coupons imported: {len(codes)}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed-event").add_argument("path", type=Path)
    sub.add_parser("seed-seats")
    sub.add_parser("import-coupons").add_argument("path", type=Path)
    sub.add_parser("hash-password")
    a = p.parse_args(argv)

    if a.cmd == "hash-password":
        pw = getpass.getpass("password: ")
        if len(pw) < 12 or pw != getpass.getpass("again: "):
            sys.exit("passwords do not match or shorter than 12 chars")
        print(hash_password(pw))
        return
    s = get_settings()
    d = db.Db(s.table_name)
    if a.cmd == "seed-event":
        seed_event(d, s.event_id, a.path)
    elif a.cmd == "seed-seats":
        seed_seats(d, s.event_id)
    elif a.cmd == "import-coupons":
        import_coupons(d, a.path)


if __name__ == "__main__":
    main()
