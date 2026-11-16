"""業務ロジック（在庫・注文・決済・受付）。HTTP 層からは独立させる。

在庫は座席単位。予約・決済確定・解放はすべて TransactWriteItems で
「座席の状態遷移」と「注文の状態遷移」を一括して行う。
"""

import csv
import hashlib
import hmac
import io
import logging
import re
import secrets
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from app import db
from app.config import Settings
from app.db import Db, TransactionCanceled, iso
from app.mailer import Mailer, MailTicket, TicketMail
from app.payments import Payments, SessionState
from app.pricing import SeatCategory, calc_total
from app.seats import all_seats, seat_label

log = logging.getLogger(__name__)

CATEGORY_NAME: dict[str, str] = {"S": "S席", "A": "A席", "W": "車椅子席"}
MAX_EMAIL_ATTEMPTS = 6  # 定期回収(5分ごと)で約30分再送する
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class Event:
    id: str
    name: str
    starts_at: str
    doors_open_at: str
    venue: str
    sales_start: str
    sales_end: str
    published: bool
    prices: dict[SeatCategory, int]
    coupon_discount: int
    max_per_order: int

    def on_sale(self, at: datetime) -> bool:
        return self.published and self.sales_start <= iso(at) < self.sales_end

    def public(self, at: datetime) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "starts_at": self.starts_at,
            "doors_open_at": self.doors_open_at,
            "venue": self.venue,
            "sales_start": self.sales_start,
            "sales_end": self.sales_end,
            "on_sale": self.on_sale(at),
            "prices": self.prices,
            "coupon_discount": self.coupon_discount,
            "max_per_order": self.max_per_order,
        }


def normalize_coupon(code: str | None) -> str | None:
    if code is None:
        return None
    c = code.strip().upper()
    return c or None


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csv_cell(v: object) -> str:
    s = str(v)
    # CSVインジェクション対策: 数式扱いされる先頭文字をエスケープ
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _jst(iso_str: str) -> str:
    from zoneinfo import ZoneInfo

    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Tokyo"))
    wd = "月火水木金土日"[dt.weekday()]
    return f"{dt.year}年{dt.month}月{dt.day}日（{wd}）{dt.hour:02d}:{dt.minute:02d}"


def purge_emails(d: Db, event_id: str, include_unsent: bool = False) -> int:
    """注文に残っているメールを削除する。

    通常は送信待ちの0円注文（PAID かつ未送信）だけ残す。include_unsent=True なら全注文から消す（公演後など）。
    """
    n = 0
    orders = d.query_all(
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :p",
        ExpressionAttributeValues={":p": db.event_pk(event_id)},
    )
    for o in orders:
        if "email" not in o:
            continue
        if not include_unsent and o["status"] == "PAID" and not o.get("email_sent"):
            continue
        d.table.update_item(Key=db.order_key(o["order_id"]), UpdateExpression="REMOVE email")
        n += 1
    return n


@dataclass
class Service:
    settings: Settings
    db: Db
    payments: Payments
    mailer: Mailer
    clock: Any = field(default=db.now)
    _event_cache: tuple[float, Event] | None = None

    # ---------- 公演・座席 ----------

    @property
    def event_id(self) -> str:
        return self.settings.event_id

    def event(self, fresh: bool = False) -> Event:
        if not fresh and self._event_cache and time.monotonic() - self._event_cache[0] < 30:
            return self._event_cache[1]
        item = self.db.get({"pk": db.event_pk(self.event_id), "sk": "META"}, consistent=False)
        if not item:
            raise ApiError(404, "not_found", "公演が見つかりません")
        ev = Event(
            id=self.event_id,
            name=item["name"],
            starts_at=item["starts_at"],
            doors_open_at=item["doors_open_at"],
            venue=item["venue"],
            sales_start=item["sales_start"],
            sales_end=item["sales_end"],
            published=bool(item.get("published", False)),
            prices=item["prices"],
            coupon_discount=item["coupon_discount"],
            max_per_order=item["max_per_order"],
        )
        self._event_cache = (time.monotonic(), ev)
        return ev

    def seat_status(self) -> dict[str, list[str]]:
        items = self.db.query_all(
            IndexName="gsi2",
            KeyConditionExpression="gsi2pk = :p",
            ExpressionAttributeValues={":p": f"SEATS#{self.event_id}"},
            ProjectionExpression="seat_id, #s",
            ExpressionAttributeNames={"#s": "status"},
        )
        return {
            "sold": [i["seat_id"] for i in items if i["status"] == "SOLD"],
            "held": [i["seat_id"] for i in items if i["status"] == "HELD"],
        }

    def coupon_exists(self, code: str | None) -> bool:
        c = normalize_coupon(code)
        if not c or len(c) > 64:
            return False
        return self.db.get(db.coupon_key(c), consistent=False) is not None

    def _validate_seats(self, seat_ids: list[str], ev: Event) -> list[tuple[str, SeatCategory]]:
        if not seat_ids or len(seat_ids) > ev.max_per_order:
            raise ApiError(400, "bad_quantity", f"座席は1〜{ev.max_per_order}席で選択してください")
        if len(set(seat_ids)) != len(seat_ids):
            raise ApiError(400, "bad_seat", "同じ座席が重複しています")
        seats = all_seats()
        unknown = [s for s in seat_ids if s not in seats]
        if unknown:
            raise ApiError(400, "bad_seat", "存在しない座席が含まれています")
        return [(s, seats[s].category) for s in seat_ids]

    @staticmethod
    def _seat_conflict(e: TransactionCanceled, seat_ids: list[str]) -> ApiError:
        if not e.only_contention():
            log.warning("seat transaction failed reasons=%s", e.reasons)
            return ApiError(503, "busy", "混み合っています。少し待ってからもう一度お試しください")
        for i in e.failed():
            if i < len(seat_ids):
                return ApiError(409, "seat_taken", f"{seat_label(seat_ids[i])} は販売済みか、他の方が購入手続き中です")
        return ApiError(409, "seat_taken", "選択した座席の一部が確保できませんでした")

    # ---------- 購入 ----------

    def checkout(self, seat_ids: list[str], coupon_code: str | None, name: str, email: str) -> dict:
        ev = self.event(fresh=True)
        now = self.clock()
        if not ev.on_sale(now):
            raise ApiError(400, "not_on_sale", "現在は販売期間外です")
        name = name.strip()
        email = email.strip()
        if not name or len(name) > 100 or CONTROL_RE.search(name):
            raise ApiError(400, "bad_name", "お名前を正しく入力してください")
        if len(email) > 254 or not EMAIL_RE.match(email):
            raise ApiError(400, "bad_email", "メールアドレスを正しく入力してください")
        seats = self._validate_seats(seat_ids, ev)
        coupon = normalize_coupon(coupon_code)
        if coupon and not self.coupon_exists(coupon):
            raise ApiError(400, "bad_coupon", "クーポンコードが無効です")

        lines, amount = calc_total(seats, len(seats) if coupon else 0, ev.prices, ev.coupon_discount)
        ordered = [line.seat_id for line in lines]
        order_id = "ord_" + secrets.token_hex(8)
        order_key = secrets.token_urlsafe(24)
        expires = now + timedelta(minutes=self.settings.hold_minutes)
        order = {
            **db.order_key(order_id),
            "order_id": order_id,
            "event_id": self.event_id,
            "channel": "online",
            "name": name,
            "seats": ordered,
            "amount": amount,
            "coupon_code": coupon,
            "coupon_count": len(seats) if coupon else 0,
            "created_at": iso(now),
            "order_key_hash": hash_secret(order_key),
            "checked_in": 0,
            "gsi1pk": db.event_pk(self.event_id),
            "gsi1sk": f"{iso(now)}#{order_id}",
        }

        if amount == 0:
            # 0円注文は Stripe を通さず即発券
            tokens = [secrets.token_urlsafe(16) for _ in ordered]
            order |= {
                "status": "PAID",
                "paid_at": iso(now),
                "tokens": tokens,
                # Stripe を通らないため、送信が成功するまでだけメールを保持する（送信成功時に削除）
                "email": email,
                "email_sent": False,
                "gsi2pk": f"EMAIL#{self.event_id}",
                "gsi2sk": iso(now),
            }
            items = [self._seat_tx(s, "AVAILABLE", "SOLD", order_id) for s in ordered]
            items.append(self._put_new(order))
            items += [self._put_new(self._ticket(t, s, order)) for t, s in zip(tokens, ordered, strict=True)]
            try:
                self.db.transact(items)
            except TransactionCanceled as e:
                raise self._seat_conflict(e, ordered) from e
            self.send_email(order_id)
            return {"order_id": order_id, "order_key": order_key}

        order |= {
            "status": "PENDING",
            "expires_at": iso(expires),
            "gsi2pk": f"PENDING#{self.event_id}",
            "gsi2sk": iso(expires),
        }
        items = [self._seat_tx(s, "AVAILABLE", "HELD", order_id, iso(expires)) for s in ordered]
        items.append(self._put_new(order))
        try:
            self.db.transact(items)
        except TransactionCanceled as e:
            raise self._seat_conflict(e, ordered) from e

        try:
            sid, url = self.payments.create_session(
                order_id=order_id,
                amount=amount,
                quantity=len(ordered),
                description="、".join(seat_label(s) for s in ordered),
                email=email,
                # Stripe 側の期限は仮押さえより少し前にして、期限後に決済が完了しないようにする
                expires_at=int(expires.timestamp()) - 60,
                success_url=f"{self.settings.site_url}/purchase/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{self.settings.site_url}/purchase/cancel?session_id={{CHECKOUT_SESSION_ID}}",
            )
        except Exception as e:
            log.exception("stripe session create failed order=%s", order_id)
            self._release(order_id, ordered)
            raise ApiError(502, "payment_unavailable", "決済の準備に失敗しました。時間をおいてお試しください") from e

        self.db.transact(
            [
                {
                    "Update": {
                        "Key": db.order_key(order_id),
                        "UpdateExpression": "SET stripe_session_id = :s",
                        "ExpressionAttributeValues": {":s": sid},
                    }
                },
                {"Put": {"Item": {**db.session_key(sid), "order_id": order_id}}},
            ]
        )
        return {"checkout_url": url}

    def _seat_tx(self, seat_id: str, frm: str, to: str, order_id: str, hold_until: str | None = None) -> dict:
        names = {"#s": "status"}
        values: dict[str, Any] = {":to": to, ":frm": frm}
        cond = "#s = :frm" if frm == "AVAILABLE" else "#s = :frm AND order_id = :oid"
        if to == "AVAILABLE":
            expr = "SET #s = :to REMOVE order_id, hold_expires_at, gsi2pk, gsi2sk"
            values[":oid"] = order_id
        else:
            values |= {":oid": order_id, ":g": f"SEATS#{self.event_id}", ":sid": seat_id}
            expr = "SET #s = :to, order_id = :oid, gsi2pk = :g, gsi2sk = :sid"
            if hold_until:
                expr += ", hold_expires_at = :h"
                values[":h"] = hold_until
            else:
                expr += " REMOVE hold_expires_at"
        return {
            "Update": {
                "Key": db.seat_key(self.event_id, seat_id),
                "UpdateExpression": expr,
                "ConditionExpression": cond,
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        }

    @staticmethod
    def _put_new(item: dict) -> dict:
        return {"Put": {"Item": item, "ConditionExpression": "attribute_not_exists(pk)"}}

    def _ticket(self, token: str, seat_id: str, order: dict, used_at: str | None = None) -> dict:
        t = {
            **db.ticket_key(token),
            "token": token,
            "order_id": order["order_id"],
            "event_id": self.event_id,
            "seat_id": seat_id,
            "holder_name": order["name"],
        }
        if used_at:
            t["used_at"] = used_at
        return t

    def _release(self, order_id: str, seat_ids: list[str]) -> bool:
        """PENDING の注文を EXPIRED にして座席を解放する。既に PENDING でなければ何もしない。"""
        items = [
            {
                "Update": {
                    "Key": db.order_key(order_id),
                    "UpdateExpression": "SET #s = :e, released_at = :t REMOVE gsi2pk, gsi2sk",
                    "ConditionExpression": "#s = :p",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {":e": "EXPIRED", ":p": "PENDING", ":t": iso(self.clock())},
                }
            }
        ]
        items += [self._seat_tx(s, "HELD", "AVAILABLE", order_id) for s in seat_ids]
        try:
            self.db.transact(items)
            return True
        except TransactionCanceled as e:
            if 0 in e.failed():
                return False
            raise

    def _fulfill(self, order: dict, session: SessionState) -> None:
        """決済完了。PAID への更新・座席の SOLD 化・チケット作成を1トランザクションで行う（冪等）。"""
        oid = order["order_id"]
        if session.amount_total is not None and session.amount_total != order["amount"]:
            log.error("amount mismatch order=%s stripe=%s db=%s", oid, session.amount_total, order["amount"])
            raise ApiError(500, "amount_mismatch", "金額が一致しません")
        now = iso(self.clock())
        tokens = [secrets.token_urlsafe(16) for _ in order["seats"]]
        items = [
            {
                "Update": {
                    "Key": db.order_key(oid),
                    "UpdateExpression": "SET #s = :paid, paid_at = :t, tokens = :tk, email_sent = :f, "
                    "gsi2pk = :g, gsi2sk = :t",
                    "ConditionExpression": "#s = :p",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {
                        ":paid": "PAID",
                        ":p": "PENDING",
                        ":t": now,
                        ":tk": tokens,
                        ":f": False,
                        ":g": f"EMAIL#{self.event_id}",
                    },
                }
            }
        ]
        items += [self._seat_tx(s, "HELD", "SOLD", oid) for s in order["seats"]]
        items += [self._put_new(self._ticket(t, s, order)) for t, s in zip(tokens, order["seats"], strict=True)]
        try:
            self.db.transact(items)
        except TransactionCanceled as e:
            current = self.db.get(db.order_key(oid))
            if current and current["status"] == "PAID":
                return  # 再送された Webhook など。既に処理済み
            if current and current["status"] == "EXPIRED":
                # 解放後に決済が完了した（通常は起きない）。座席は保証できないため手動返金の対象にする
                log.error("PAID_AFTER_RELEASE order=%s session=%s: refund manually", oid, session.id)
                self.db.table.update_item(
                    Key=db.order_key(oid),
                    UpdateExpression="SET needs_refund = :t",
                    ExpressionAttributeValues={":t": True},
                )
                return
            log.error("fulfill failed order=%s status=%s reasons=%s", oid, current and current["status"], e.reasons)
            raise
        self.send_email(oid, session.email)

    def reconcile(self, order: dict, force_expire: bool) -> str:
        """Stripe 側の状態に合わせて注文を確定または解放する。戻り値は最終状態。"""
        oid = order["order_id"]
        if order["status"] != "PENDING":
            return order["status"]
        sid = order.get("stripe_session_id")
        if not sid:
            # セッション作成前に落ちた注文。購入者は決済画面に到達していない
            if force_expire:
                self._release(oid, order["seats"])
                return "EXPIRED"
            return "PENDING"
        s = self.payments.retrieve(sid)
        if s.status == "open" and force_expire:
            try:
                s = self.payments.expire(sid)
            except Exception:
                log.warning("expire failed order=%s; re-checking", oid, exc_info=True)
                s = self.payments.retrieve(sid)
        if s.status == "complete" and s.payment_status in ("paid", "no_payment_required"):
            self._fulfill(order, s)
            return "PAID"
        if s.status == "expired":
            self._release(oid, order["seats"])
            return "EXPIRED"
        return "PENDING"

    def _order_by_session(self, session_id: str) -> dict:
        m = self.db.get(db.session_key(session_id)) if 0 < len(session_id) <= 255 else None
        order = self.db.get(db.order_key(m["order_id"])) if m else None
        if not order:
            raise ApiError(404, "not_found", "注文が見つかりません")
        return order

    def cancel_checkout(self, session_id: str) -> None:
        self.reconcile(self._order_by_session(session_id), force_expire=True)

    def handle_webhook(self, event: dict) -> None:
        etype = event.get("type")
        if etype not in ("checkout.session.completed", "checkout.session.expired"):
            return
        obj = event["data"]["object"]
        m = self.db.get(db.session_key(obj["id"]))
        oid = m["order_id"] if m else (obj.get("metadata") or {}).get("order_id")
        order = self.db.get(db.order_key(oid)) if oid else None
        if not order:
            log.error("webhook for unknown order session=%s", obj["id"])
            return
        if order.get("stripe_session_id") not in (None, obj["id"]):
            log.error("session mismatch order=%s", oid)
            return
        order.setdefault("stripe_session_id", obj["id"])
        # 内容は Stripe から取り直して判定する（イベント本体の順序・重複に依存しない）
        self.reconcile(order, force_expire=False)

    def sweep(self) -> dict[str, int]:
        """定期回収: 期限切れの PENDING を確定/解放し、未送信メールを再送する。"""
        now = iso(self.clock())
        stale = self.db.query_all(
            IndexName="gsi2",
            KeyConditionExpression="gsi2pk = :p AND gsi2sk < :t",
            ExpressionAttributeValues={":p": f"PENDING#{self.event_id}", ":t": now},
        )
        result: Counter[str] = Counter()
        for o in stale:
            try:
                order = self.db.get(db.order_key(o["order_id"]))
                if order:
                    result[self.reconcile(order, force_expire=True)] += 1
            except Exception:
                log.exception("sweep reconcile failed order=%s", o["order_id"])
                result["error"] += 1
        unsent = self.db.query_all(
            IndexName="gsi2",
            KeyConditionExpression="gsi2pk = :p AND gsi2sk < :t",
            ExpressionAttributeValues={":p": f"EMAIL#{self.event_id}", ":t": iso(self.clock() - timedelta(minutes=2))},
        )
        for o in unsent:
            if self.send_email(o["order_id"]):
                result["email"] += 1
        return dict(result)

    # ---------- 照会 ----------

    def _ticket_info(self, t: dict, ev: Event) -> dict:
        s = all_seats().get(t["seat_id"])
        return {
            "token": t["token"],
            "event_name": ev.name,
            "starts_at": ev.starts_at,
            "doors_open_at": ev.doors_open_at,
            "venue": ev.venue,
            "seat_label": seat_label(t["seat_id"]),
            "category": s.category if s else "S",
            "holder_name": t["holder_name"],
            "used_at": t.get("used_at"),
        }

    def _tickets(self, order: dict) -> list[dict]:
        tokens = order.get("tokens") or []
        if not tokens:
            return []
        res = self.db.client.batch_get_item(
            RequestItems={self.db.table.name: {"Keys": [db.ticket_key(t) for t in tokens], "ConsistentRead": True}}
        )
        got = {i["token"]: db.plain(i) for i in res["Responses"][self.db.table.name]}
        # batch_get の未処理分は個別に取り直す
        for t in tokens:
            if t not in got and (item := self.db.get(db.ticket_key(t))):
                got[t] = item
        return [got[t] for t in tokens if t in got]

    def _order_info(self, order: dict) -> dict:
        ev = self.event()
        return {
            "order_id": order["order_id"],
            "status": order["status"],
            "tickets": [self._ticket_info(t, ev) for t in self._tickets(order)] if order["status"] == "PAID" else [],
        }

    def order_by_session(self, session_id: str) -> dict:
        order = self._order_by_session(session_id)
        if order["status"] == "PENDING" and order.get("stripe_session_id"):
            # Webhook より先に完了画面に戻ってきた場合に備え、Stripe に直接確認する
            self.reconcile(order, force_expire=False)
            order = self.db.get(db.order_key(order["order_id"])) or order
        return self._order_info(order)

    def order_by_key(self, order_id: str, key: str) -> dict:
        order = self.db.get(db.order_key(order_id)) if 0 < len(order_id) <= 64 else None
        if not order or not key or not hmac.compare_digest(order.get("order_key_hash", ""), hash_secret(key)):
            raise ApiError(404, "not_found", "注文が見つかりません")
        return self._order_info(order)

    def ticket(self, token: str) -> dict:
        t = self.db.get(db.ticket_key(token), consistent=False) if 0 < len(token) <= 64 else None
        if not t:
            raise ApiError(404, "not_found", "チケットが見つかりません")
        return self._ticket_info(t, self.event())

    # ---------- メール ----------

    def _recipient(self, order: dict, email: str | None) -> str:
        """送信先。有料注文のメールはDBに保存しないので Stripe のセッションから取得する。"""
        to = email or order.get("email")
        if not to and (sid := order.get("stripe_session_id")):
            to = self.payments.retrieve(sid).email
        if not to:
            raise RuntimeError("no recipient")
        return to

    @staticmethod
    def _can_email(order: dict | None) -> bool:
        return bool(
            order
            and order["status"] == "PAID"
            and order.get("channel") == "online"
            and (order.get("email") or order.get("stripe_session_id"))
        )

    def send_email(self, order_id: str, email: str | None = None) -> bool:
        order = self.db.get(db.order_key(order_id))
        if not order or not self._can_email(order):
            return False
        ev = self.event()
        tickets = self._tickets(order)
        mail = TicketMail(
            to="",
            holder_name=order["name"],
            event_name=ev.name,
            starts_at_jst=_jst(ev.starts_at),
            doors_open_jst=_jst(ev.doors_open_at)[-5:],
            venue=ev.venue,
            tickets=[
                MailTicket(
                    url=f"{self.settings.site_url}/t/{t['token']}",
                    seat_label=seat_label(t["seat_id"]),
                    category_name=CATEGORY_NAME[all_seats()[t["seat_id"]].category],
                )
                for t in tickets
            ],
        )
        try:
            self.mailer.send(replace(mail, to=self._recipient(order, email)))
        except Exception as e:
            # 例外メッセージに宛先が含まれることがある(SES など)ため、型とエラーコードだけ記録する
            reason = type(e).__name__
            if isinstance(err := getattr(e, "response", None), dict):
                reason += f"/{err.get('Error', {}).get('Code', '')}"
            attempts = order.get("email_attempts", 0) + 1
            give_up = attempts >= MAX_EMAIL_ATTEMPTS
            # 送れなかったメールは定期回収で再送。上限に達したら再送対象から外し、手動対応（管理画面から再送）に回す
            self.db.table.update_item(
                Key=db.order_key(order_id),
                UpdateExpression="SET email_attempts = :n" + (" REMOVE gsi2pk, gsi2sk" if give_up else ""),
                ExpressionAttributeValues={":n": attempts},
            )
            if give_up:
                log.error("EMAIL_GAVE_UP order=%s attempts=%s reason=%s", order_id, attempts, reason)
            else:
                log.warning("send email failed order=%s attempts=%s reason=%s", order_id, attempts, reason)
            return False
        self.db.table.update_item(
            Key=db.order_key(order_id),
            # 0円注文で一時保存していたメールも送信成功時に消す
            UpdateExpression="SET email_sent = :t, email_sent_at = :at, email_attempts = :z "
            "REMOVE gsi2pk, gsi2sk, email",
            ExpressionAttributeValues={":t": True, ":at": iso(self.clock()), ":z": 0},
        )
        return True

    # ---------- スタッフ ----------

    def checkin(self, token: str) -> dict:
        ev = self.event()
        t = self.db.get(db.ticket_key(token)) if 0 < len(token) <= 64 else None
        if not t:
            return {"result": "invalid"}
        for attempt in range(4):
            now = iso(self.clock())
            try:
                self.db.transact(
                    [
                        {
                            "Update": {
                                "Key": db.ticket_key(token),
                                "UpdateExpression": "SET used_at = :t",
                                "ConditionExpression": "attribute_exists(pk) AND attribute_not_exists(used_at)",
                                "ExpressionAttributeValues": {":t": now},
                            }
                        },
                        self._add_checked_in(t["order_id"], 1),
                    ]
                )
            except TransactionCanceled as e:
                cond = e.condition_failed()
                if 0 in cond:
                    t = self.db.get(db.ticket_key(token)) or t
                    return {"result": "used", "ticket": self._ticket_info(t, ev)}
                if 1 in cond:
                    return {"result": "invalid"}  # 注文が PAID でない（返金済みなど）
                # 同じ注文の別チケットを同時に受付した（TransactionConflict）など。少し待って再試行
                log.info("checkin retry token=%s reasons=%s", token[:6], e.reasons)
                time.sleep(0.05 * (attempt + 1))
                continue
            t["used_at"] = now
            return {"result": "ok", "ticket": self._ticket_info(t, ev)}
        raise ApiError(503, "busy", "混み合っています。もう一度読み取ってください")

    @staticmethod
    def _add_checked_in(order_id: str, n: int) -> dict:
        return {
            "Update": {
                "Key": db.order_key(order_id),
                "UpdateExpression": "ADD checked_in :n",
                "ConditionExpression": "#s = :paid",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": {":n": n, ":paid": "PAID"},
            }
        }

    def checkin_order(self, order_id: str) -> None:
        for _ in range(3):
            order = self.db.get(db.order_key(order_id)) if 0 < len(order_id) <= 64 else None
            if not order or order["status"] != "PAID":
                raise ApiError(404, "not_found", "注文が見つかりません")
            unused = [t["token"] for t in self._tickets(order) if not t.get("used_at")]
            if not unused:
                return
            now = iso(self.clock())
            items = [
                {
                    "Update": {
                        "Key": db.ticket_key(tok),
                        "UpdateExpression": "SET used_at = :t",
                        "ConditionExpression": "attribute_not_exists(used_at)",
                        "ExpressionAttributeValues": {":t": now},
                    }
                }
                for tok in unused
            ]
            items.append(self._add_checked_in(order_id, len(unused)))
            try:
                self.db.transact(items)
                return
            except TransactionCanceled:
                time.sleep(0.05)
                continue  # 同時にQR受付された。読み直して再試行
        raise ApiError(409, "conflict", "処理が競合しました。もう一度お試しください")

    def search_orders(self, q: str) -> list[dict]:
        s = q.strip().lower()
        if not s:
            return []
        hits = [
            o for o in self._all_orders() if o["status"] == "PAID" and (s in o["name"].lower() or s in o["order_id"])
        ]
        return [self._admin_order(o) for o in hits[:50]]

    def box_office(self, seat_ids: list[str], coupon_count: int) -> dict:
        ev = self.event(fresh=True)
        seats = self._validate_seats(seat_ids, ev)
        if not 0 <= coupon_count <= len(seats):
            raise ApiError(400, "bad_coupon_count", "クーポン枚数が不正です")
        lines, amount = calc_total(seats, coupon_count, ev.prices, ev.coupon_discount)
        ordered = [line.seat_id for line in lines]
        now = iso(self.clock())
        order_id = "ord_" + secrets.token_hex(8)
        tokens = [secrets.token_urlsafe(16) for _ in ordered]
        order = {
            **db.order_key(order_id),
            "order_id": order_id,
            "event_id": self.event_id,
            "channel": "boxoffice",
            "name": "当日券",
            "seats": ordered,
            "amount": amount,
            "coupon_code": None,
            "coupon_count": coupon_count,
            "created_at": now,
            "paid_at": now,
            "status": "PAID",
            "tokens": tokens,
            "checked_in": len(ordered),
            "gsi1pk": db.event_pk(self.event_id),
            "gsi1sk": f"{now}#{order_id}",
        }
        items = [self._seat_tx(s, "AVAILABLE", "SOLD", order_id) for s in ordered]
        items.append(self._put_new(order))
        # 当日券は販売と同時に入場済み
        items += [self._put_new(self._ticket(t, s, order, used_at=now)) for t, s in zip(tokens, ordered, strict=True)]
        try:
            self.db.transact(items)
        except TransactionCanceled as e:
            raise self._seat_conflict(e, ordered) from e
        return {"order_id": order_id, "amount": amount}

    # ---------- 管理 ----------

    def _all_orders(self) -> list[dict]:
        return self.db.query_all(
            IndexName="gsi1",
            KeyConditionExpression="gsi1pk = :p",
            ExpressionAttributeValues={":p": db.event_pk(self.event_id)},
            ScanIndexForward=False,
        )

    def purge_emails(self, include_unsent: bool = False) -> int:
        return purge_emails(self.db, self.event_id, include_unsent)

    @staticmethod
    def _admin_order(o: dict) -> dict:
        coupon = o.get("coupon_code") or ("(当日)" if o.get("coupon_count") else None)
        return {
            "order_id": o["order_id"],
            "created_at": o["created_at"],
            "channel": o["channel"],
            "name": o["name"],
            "seats": o["seats"],
            "amount": o["amount"],
            "coupon_code": coupon,
            "status": o["status"],
            "checked_in": o.get("checked_in", 0),
            "can_resend": Service._can_email(o),
        }

    def admin_orders(self) -> list[dict]:
        # needs_refund: 解放後に決済が完了した注文（要返金）も一覧に出す
        return [self._admin_order(o) for o in self._all_orders() if o["status"] != "EXPIRED" or o.get("needs_refund")]

    def summary(self) -> dict:
        seats = all_seats()
        st = self.seat_status()
        sold: dict[str, int] = {"S": 0, "A": 0, "W": 0}
        for sid in st["sold"]:
            sold[seats[sid].category] += 1
        paid = [o for o in self._all_orders() if o["status"] == "PAID"]

        def revenue(ch: Literal["online", "boxoffice"]) -> int:
            return sum(o["amount"] for o in paid if o["channel"] == ch)

        return {
            "total_seats": len(seats),
            "sold": sold,
            "held": len(st["held"]),
            "revenue_online": revenue("online"),
            "revenue_boxoffice": revenue("boxoffice"),
            "checked_in": sum(o.get("checked_in", 0) for o in paid),
            "coupon_used": sum(o.get("coupon_count", 0) for o in paid),
        }

    def orders_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        w.writerow(["注文ID", "日時", "経路", "氏名", "座席", "金額", "クーポン", "入場済"])
        for o in self._all_orders():
            if o["status"] != "PAID":
                continue
            a = self._admin_order(o)
            w.writerow(
                csv_cell(v)
                for v in (
                    a["order_id"],
                    _jst(a["created_at"]),
                    a["channel"],
                    a["name"],
                    " / ".join(seat_label(s) for s in a["seats"]),
                    a["amount"],
                    a["coupon_code"] or "",
                    a["checked_in"],
                )
            )
        return "﻿" + buf.getvalue()

    def resend(self, order_id: str) -> None:
        order = self.db.get(db.order_key(order_id)) if 0 < len(order_id) <= 64 else None
        if not self._can_email(order):
            raise ApiError(404, "not_found", "メール送信できる注文が見つかりません")
        if not self.send_email(order_id):
            raise ApiError(502, "mail_failed", "メール送信に失敗しました")
