import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app import cli, db
from app.config import Settings
from app.mailer import TicketMail
from app.payments import SessionState
from app.service import Service

EVENT_ID = "evt_test"


class FakePayments:
    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.fail_create = False

    def create_session(self, *, order_id, amount, description, quantity, email, expires_at, success_url, cancel_url):
        if self.fail_create:
            raise RuntimeError("stripe down")
        sid = f"cs_{len(self.sessions) + 1}"
        self.sessions[sid] = {"status": "open", "payment_status": "unpaid", "amount": amount, "order_id": order_id}
        return sid, f"https://checkout.stripe.test/{sid}"

    def _state(self, sid: str) -> SessionState:
        s = self.sessions[sid]
        return SessionState(sid, s["status"], s["payment_status"], s["amount"], s["order_id"])

    def retrieve(self, session_id):
        return self._state(session_id)

    def expire(self, session_id):
        s = self.sessions[session_id]
        if s["status"] != "open":
            raise RuntimeError("session is not open")
        s["status"] = "expired"
        return self._state(session_id)

    def pay(self, sid: str) -> None:
        self.sessions[sid] |= {"status": "complete", "payment_status": "paid"}

    def verify_webhook(self, payload, signature):
        if signature != "valid":
            raise ValueError("bad signature")


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[TicketMail] = []
        self.fail = False

    def send(self, mail: TicketMail) -> None:
        if self.fail:
            raise RuntimeError("ses down")
        self.sent.append(mail)


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2027, 1, 10, 3, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, minutes: int) -> None:
        self.t += timedelta(minutes=minutes)


def create_table(resource, name: str) -> None:
    resource.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": n, "AttributeType": "S"} for n in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": idx,
                "KeySchema": [
                    {"AttributeName": f"{idx}pk", "KeyType": "HASH"},
                    {"AttributeName": f"{idx}sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for idx in ("gsi1", "gsi2")
        ],
    )


@pytest.fixture
def env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    for k, v in {
        "STAFF_KEY": "staff-old,staff-new",
        "JWT_SECRET": "jwt-secret-for-tests-0123456789abcdef",
        "ADMIN_PASSWORD_HASH": "",
    }.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        resource = boto3.resource("dynamodb")
        create_table(resource, "t")
        d = db.Db("t", resource)
        ev = json.loads((Path(__file__).parents[1] / "event.json").read_text())
        ev["published"] = True
        # 実際の公演日程に依存しないよう、テスト用の日程で上書きする（Clock は販売期間内）
        ev.update(
            starts_at="2027-03-20T05:00:00Z",
            doors_open_at="2027-03-20T04:15:00Z",
            sales_start="2026-12-01T01:00:00Z",
            sales_end="2027-03-20T04:00:00Z",
        )
        p = tmp_path / "event.json"
        p.write_text(json.dumps(ev))
        cli.seed_event(d, EVENT_ID, p)
        cli.seed_seats(d, EVENT_ID)
        (tmp_path / "c.txt").write_text(" sample500 \nFRIEND\n\n")
        cli.import_coupons(d, tmp_path / "c.txt")
        yield d


@pytest.fixture
def svc(env) -> Service:
    settings = Settings(
        table_name="t", event_id=EVENT_ID, site_url="https://tix.test", mail_from="f@x", ssm_prefix=None
    )
    return Service(settings, env, FakePayments(), FakeMailer(), clock=Clock())


@pytest.fixture
def client(svc: Service):
    from app.main import app, get_service

    app.dependency_overrides[get_service] = lambda: svc
    yield TestClient(app)
    app.dependency_overrides.clear()
