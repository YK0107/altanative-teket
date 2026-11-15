from app import auth


def test_public_endpoints(client):
    r = client.get("/api/event")
    assert r.status_code == 200 and r.json()["on_sale"] is True and r.json()["prices"]["S"] == 1000
    assert "max-age=30" in r.headers["cache-control"]
    r = client.get("/api/event/seats")
    assert r.json() == {"sold": [], "held": []} and "max-age=3" in r.headers["cache-control"]
    assert client.post("/api/coupons/validate", json={"code": "friend"}).json() == {"valid": True}
    assert client.get("/api/tickets/nope").status_code == 404


def test_checkout_errors_have_code(client):
    r = client.post("/api/checkout", json={"seat_ids": [], "name": "a", "email": "a@example.com"})
    assert r.status_code == 400 and r.json()["code"] == "bad_quantity"
    r = client.post("/api/checkout", json={"seat_ids": "x"})
    assert r.status_code == 400 and r.json()["code"] == "bad_request"
    assert client.post("/api/checkout", json={"seat_ids": ["1-A-13"], "name": "a", "email": "a@example.com"}).is_success
    r = client.post("/api/checkout", json={"seat_ids": ["1-A-13"], "name": "b", "email": "b@example.com"})
    assert r.status_code == 409 and r.json()["code"] == "seat_taken"
    assert r.headers["cache-control"] == "no-store"


def test_webhook_signature(client, svc):
    r = client.post("/api/stripe/webhook", content=b"{}", headers={"stripe-signature": "bad"})
    assert r.status_code == 400
    r = client.post("/api/stripe/webhook", content=b'{"type":"ping"}', headers={"stripe-signature": "valid"})
    assert r.status_code == 200


def test_staff_key_and_rotation(client):
    assert client.post("/api/staff/checkin", json={"token": "x"}).status_code == 401
    assert client.post("/api/staff/checkin", json={"token": "x"}, headers={"X-Staff-Key": "wrong"}).status_code == 401
    for key in ("staff-old", "staff-new"):
        r = client.post("/api/staff/checkin", json={"token": "x"}, headers={"X-Staff-Key": key})
        assert r.json() == {"result": "invalid"}
    r = client.post(
        "/api/staff/boxoffice", json={"seat_ids": ["1-A-13"], "coupon_count": "1"}, headers={"X-Staff-Key": "staff-new"}
    )
    assert r.status_code == 400  # 枚数は整数のみ


def test_admin_login(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", auth.hash_password("correct horse battery"))
    assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    assert client.get("/api/admin/summary").status_code == 401
    assert client.get("/api/admin/summary", headers={"Authorization": "Bearer forged"}).status_code == 401
    token = client.post("/api/admin/login", json={"password": "correct horse battery"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    s = client.get("/api/admin/summary", headers=h).json()
    assert s["total_seats"] == 2003
    assert client.get("/api/admin/orders", headers=h).json() == []
    r = client.get("/api/admin/orders.csv", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
