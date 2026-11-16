import pytest

from app import db
from app.service import ApiError, Service


def _pay(svc: Service, seats=("1-A-13",), coupon=None, name="山田 太郎"):
    res = svc.checkout(list(seats), coupon, name, "a@example.com")
    assert res["checkout_url"].startswith("https://checkout.stripe.test/")
    sid = res["checkout_url"].rsplit("/", 1)[1]
    return sid


def _webhook(svc: Service, etype: str, sid: str):
    svc.handle_webhook({"type": etype, "data": {"object": {"id": sid, "metadata": {}}}})


def _order(svc: Service, sid: str) -> dict:
    m = svc.db.get(db.session_key(sid))
    assert m
    o = svc.db.get(db.order_key(m["order_id"]))
    assert o
    return o


def test_checkout_holds_seats_and_payment_issues_tickets(svc):
    sid = _pay(svc, ["1-A-13", "3-A-31"])
    st = svc.seat_status()
    assert "1-A-13" in st["held"] and not st["sold"]
    svc.payments.pay(sid)
    _webhook(svc, "checkout.session.completed", sid)
    _webhook(svc, "checkout.session.completed", sid)  # 再送されても冪等
    o = _order(svc, sid)
    assert o["status"] == "PAID" and o["email_sent"] is True and "gsi2pk" not in o
    assert len(o["tokens"]) == len(o["seats"])
    assert len(svc.mailer.sent) == 1 and svc.mailer.sent[0].to == "a@example.com"
    assert "email" not in o  # メールはDBに保存しない（Stripe から取得）
    assert "email" not in info_keys(svc, sid)
    assert sorted(svc.seat_status()["sold"]) == sorted(o["seats"])
    assert svc.payments.sessions[sid]["amount"] == 1500
    info = svc.order_by_session(sid)
    assert info["status"] == "PAID" and len(info["tickets"]) == len(o["seats"])


def info_keys(svc: Service, sid: str) -> set[str]:
    return set(svc.order_by_session(sid))


def test_seat_taken_conflict(svc):
    _pay(svc, ["1-A-13"])
    with pytest.raises(ApiError) as e:
        svc.checkout(["1-A-14", "1-A-13"], None, "別人", "b@example.com")
    assert e.value.status == 409 and e.value.code == "seat_taken" and "1階 A列 13番" in e.value.message
    # 失敗した注文の他の座席は確保されていない
    assert "1-A-14" not in svc.seat_status()["held"]


def test_cancel_releases_immediately(svc):
    sid = _pay(svc)
    svc.cancel_checkout(sid)
    assert _order(svc, sid)["status"] == "EXPIRED"
    assert svc.seat_status() == {"sold": [], "held": []}
    svc.checkout(["1-A-13"], None, "次の人", "c@example.com")  # すぐ買える


def test_cancel_after_payment_fulfills_instead(svc):
    sid = _pay(svc)
    svc.payments.pay(sid)  # 決済直後に cancel_url を開かれても解放しない
    svc.cancel_checkout(sid)
    assert _order(svc, sid)["status"] == "PAID"


def test_sweep_reclaims_stale_and_completes_missed_webhooks(svc):
    lost = _pay(svc, ["1-A-13"])
    paid = _pay(svc, ["1-A-14"])
    svc.payments.pay(paid)  # Webhook が届かなかった
    svc.clock.advance(10)
    assert svc.sweep() == {}  # 期限前は何もしない
    svc.clock.advance(30)
    assert svc.sweep() == {"EXPIRED": 1, "PAID": 1}
    assert _order(svc, lost)["status"] == "EXPIRED"
    assert _order(svc, paid)["status"] == "PAID"
    assert svc.seat_status() == {"sold": ["1-A-14"], "held": []}


def test_stripe_failure_releases_hold(svc):
    svc.payments.fail_create = True
    with pytest.raises(ApiError) as e:
        svc.checkout(["1-A-13"], None, "山田", "a@example.com")
    assert e.value.status == 502
    assert svc.seat_status() == {"sold": [], "held": []}


def test_free_order_skips_stripe(svc):
    res = svc.checkout(["WC-1"], " sample500 ", "車椅子 利用者", "w@example.com")
    assert set(res) == {"order_id", "order_key"}
    assert not svc.payments.sessions
    info = svc.order_by_key(res["order_id"], res["order_key"])
    assert info["status"] == "PAID" and info["tickets"][0]["category"] == "W"
    with pytest.raises(ApiError):
        svc.order_by_key(res["order_id"], "wrong")
    assert len(svc.mailer.sent) == 1 and svc.mailer.sent[0].to == "w@example.com"
    # Stripe を通らない注文も、送信後はメールを残さない
    o = svc.db.get(db.order_key(res["order_id"]))
    assert o and "email" not in o and o["email_sent"] is True


def test_free_order_keeps_email_until_sent(svc):
    svc.mailer.fail = True
    res = svc.checkout(["WC-1"], "SAMPLE500", "車椅子 利用者", "w@example.com")
    o = svc.db.get(db.order_key(res["order_id"]))
    assert o and o["email"] == "w@example.com"
    svc.mailer.fail = False
    svc.resend(res["order_id"])
    o = svc.db.get(db.order_key(res["order_id"]))
    assert o and "email" not in o and svc.mailer.sent[-1].to == "w@example.com"
    with pytest.raises(ApiError):
        svc.resend(res["order_id"])  # 宛先を保持していないので再送不可


def test_coupon_amount_and_validation(svc):
    sid = _pay(svc, ["1-A-13", "1-A-14"], coupon="friend")
    assert svc.payments.sessions[sid]["amount"] == 1000
    with pytest.raises(ApiError) as e:
        svc.checkout(["1-A-15"], "NOPE", "山田", "a@example.com")
    assert e.value.code == "bad_coupon"


def test_input_validation(svc):
    for seats, name, email in [
        ([], "a", "a@example.com"),
        ([f"1-A-{i}" for i in range(1, 12)], "a", "a@example.com"),
        (["1-A-13", "1-A-13"], "a", "a@example.com"),
        (["X-1"], "a", "a@example.com"),
        (["1-A-13"], " ", "a@example.com"),
        (["1-A-13"], "a", "not-an-email"),
        (["1-A-13"], "a", "a@example.com\r\nBcc: x@y.z"),
    ]:
        with pytest.raises(ApiError):
            svc.checkout(seats, None, name, email)


def test_not_on_sale(svc):
    svc.clock.advance(60 * 24 * 365)
    with pytest.raises(ApiError) as e:
        svc.checkout(["1-A-13"], None, "山田", "a@example.com")
    assert e.value.code == "not_on_sale"


def test_checkin_ok_then_used_then_invalid(svc):
    sid = _pay(svc)
    svc.payments.pay(sid)
    _webhook(svc, "checkout.session.completed", sid)
    token = _order(svc, sid)["tokens"][0]
    assert svc.checkin(token)["result"] == "ok"
    r = svc.checkin(token)
    assert r["result"] == "used" and r["ticket"]["used_at"]
    assert svc.checkin("nope")["result"] == "invalid"
    assert _order(svc, sid)["checked_in"] == 1


def test_checkin_order_and_search(svc):
    sid = _pay(svc, ["1-A-13", "1-A-14", "1-A-15"], name="佐藤 花子")
    svc.payments.pay(sid)
    _webhook(svc, "checkout.session.completed", sid)
    o = _order(svc, sid)
    svc.checkin(o["tokens"][0])
    hits = svc.search_orders("佐藤")
    assert [h["order_id"] for h in hits] == [o["order_id"]]
    svc.checkin_order(o["order_id"])
    assert _order(svc, sid)["checked_in"] == 3
    svc.checkin_order(o["order_id"])  # 2回目は何もしない
    assert _order(svc, sid)["checked_in"] == 3


def test_box_office(svc):
    res = svc.box_office(["1-A-13", "3-A-31"], 1)
    assert res["amount"] == 1000  # 高い席(S)からクーポン適用: (1000-500) + 500
    s = svc.summary()
    assert (
        s["sold"] == {"S": 1, "A": 1, "W": 0}
        and s["revenue_boxoffice"] == 1000
        and s["checked_in"] == 2
        and s["coupon_used"] == 1
    )
    with pytest.raises(ApiError) as e:
        svc.box_office(["1-A-13"], 0)
    assert e.value.status == 409
    with pytest.raises(ApiError):
        svc.box_office(["1-A-20"], 2)


def test_email_retry_via_sweep(svc):
    svc.mailer.fail = True
    sid = _pay(svc)
    svc.payments.pay(sid)
    _webhook(svc, "checkout.session.completed", sid)
    assert _order(svc, sid)["status"] == "PAID" and _order(svc, sid)["email_sent"] is False
    svc.mailer.fail = False
    svc.clock.advance(5)
    assert svc.sweep() == {"email": 1}
    assert _order(svc, sid)["email_sent"] is True
    assert svc.mailer.sent[-1].to == "a@example.com"  # 再送時も Stripe から宛先を取得


def test_resend_paid_order_uses_stripe_email(svc):
    sid = _pay(svc)
    svc.payments.pay(sid)
    _webhook(svc, "checkout.session.completed", sid)
    svc.resend(_order(svc, sid)["order_id"])
    assert [m.to for m in svc.mailer.sent] == ["a@example.com", "a@example.com"]
    assert "email" not in _order(svc, sid)
    assert "メール" not in svc.orders_csv().splitlines()[0]


def test_csv_escapes_formula(svc):
    sid = _pay(svc, name="=HYPERLINK(1)")
    svc.payments.pay(sid)
    _webhook(svc, "checkout.session.completed", sid)
    csv = svc.orders_csv()
    assert csv.startswith("﻿") and '"\'=HYPERLINK(1)"' in csv


def test_expired_webhook_releases(svc):
    sid = _pay(svc)
    svc.payments.sessions[sid]["status"] = "expired"
    _webhook(svc, "checkout.session.expired", sid)
    assert _order(svc, sid)["status"] == "EXPIRED"
    assert svc.seat_status()["held"] == []


def _flaky_transact(svc: Service, reasons_seq: list[list[str]]):
    from app.db import TransactionCanceled

    real = svc.db.transact

    def transact(items):
        if reasons_seq:
            raise TransactionCanceled(reasons_seq.pop(0))
        return real(items)

    svc.db.transact = transact


def test_checkin_retries_on_transaction_conflict(svc):
    sid = _pay(svc)
    svc.payments.pay(sid)
    _webhook(svc, "checkout.session.completed", sid)
    token = _order(svc, sid)["tokens"][0]
    _flaky_transact(svc, [["None", "TransactionConflict"], ["TransactionConflict", "None"]])
    assert svc.checkin(token)["result"] == "ok"
    assert _order(svc, sid)["checked_in"] == 1


def test_throttled_checkout_is_not_seat_taken(svc):
    _flaky_transact(svc, [["ThrottlingError", "None"]])
    with pytest.raises(ApiError) as e:
        svc.checkout(["1-A-13"], None, "山田", "a@example.com")
    assert e.value.status == 503


def test_email_gives_up_after_max_attempts(svc):
    from app.service import MAX_EMAIL_ATTEMPTS

    svc.mailer.fail = True
    sid = _pay(svc)
    svc.payments.pay(sid)
    _webhook(svc, "checkout.session.completed", sid)
    for _ in range(MAX_EMAIL_ATTEMPTS):
        svc.clock.advance(5)
        svc.sweep()
    o = _order(svc, sid)
    assert o["email_attempts"] == MAX_EMAIL_ATTEMPTS and "gsi2pk" not in o and o["email_sent"] is False


def test_seed_event_normalizes_timezone(env, tmp_path):
    import json

    from app import cli

    p = tmp_path / "e.json"
    data = json.loads((tmp_path / "event.json").read_text())
    data["sales_start"] = "2026-12-01T10:00:00+09:00"
    p.write_text(json.dumps(data))
    cli.seed_event(env, "evt_tz", p)
    assert env.get({"pk": "EVENT#evt_tz", "sk": "META"})["sales_start"] == "2026-12-01T01:00:00Z"


def test_purge_emails_and_can_resend(svc):
    svc.mailer.fail = True
    pending = svc.checkout(["WC-1"], "SAMPLE500", "未送信", "w@example.com")["order_id"]
    svc.mailer.fail = False
    sent = svc.checkout(["WC-2"], "SAMPLE500", "送信済", "x@example.com")["order_id"]
    # 旧データ（メールを保存していた頃の送信済み注文）を再現
    svc.db.table.update_item(
        Key=db.order_key(sent), UpdateExpression="SET email = :e", ExpressionAttributeValues={":e": "x@example.com"}
    )
    assert svc.purge_emails() == 1  # 送信待ちの0円注文は残す
    assert (svc.db.get(db.order_key(pending)) or {})["email"] == "w@example.com"
    assert "email" not in (svc.db.get(db.order_key(sent)) or {})
    rows = {o["order_id"]: o["can_resend"] for o in svc.admin_orders()}
    assert rows == {pending: True, sent: False}
    assert svc.purge_emails(include_unsent=True) == 1
    assert "email" not in (svc.db.get(db.order_key(pending)) or {})
