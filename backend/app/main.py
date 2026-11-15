"""HTTP API（FastAPI）と Lambda エントリポイント。"""

import json
import logging
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel, Field, StrictInt

from app import auth
from app.config import get_settings
from app.db import get_db
from app.mailer import get_mailer
from app.payments import get_payments
from app.service import ApiError, Service

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)


@lru_cache
def get_service() -> Service:
    return Service(get_settings(), get_db(), get_payments(), get_mailer())


Svc = Annotated[Service, Depends(get_service)]

app = FastAPI(title="teket-alt", docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError) -> JSONResponse:
    return JSONResponse({"code": e.code, "message": e.message}, status_code=e.status)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, e: RequestValidationError) -> JSONResponse:
    return JSONResponse({"code": "bad_request", "message": "入力内容が不正です"}, status_code=400)


@app.middleware("http")
async def _no_store(request: Request, call_next: Any) -> Response:
    res = await call_next(request)
    res.headers.setdefault("Cache-Control", "no-store")
    return res


def _cache(res: Response, seconds: int) -> None:
    res.headers["Cache-Control"] = f"public, max-age={seconds}"


def require_staff(x_staff_key: Annotated[str | None, Header()] = None) -> None:
    if not auth.verify_staff_key(x_staff_key):
        raise ApiError(401, "unauthorized", "受付URLが無効です。最新の受付URLを開き直してください")


def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    if not auth.verify_admin_token(authorization):
        raise ApiError(401, "unauthorized", "ログインし直してください")


Staff = Depends(require_staff)
Admin = Depends(require_admin)


class CheckoutBody(BaseModel):
    seat_ids: list[str] = Field(max_length=50)
    coupon_code: str | None = Field(default=None, max_length=64)
    name: str = Field(max_length=200)
    email: str = Field(max_length=300)


class CouponBody(BaseModel):
    code: str = Field(max_length=64)


class SessionBody(BaseModel):
    session_id: str = Field(max_length=255)


class TokenBody(BaseModel):
    token: str = Field(max_length=2000)


class BoxOfficeBody(BaseModel):
    seat_ids: list[str] = Field(max_length=50)
    coupon_count: StrictInt


class LoginBody(BaseModel):
    password: str = Field(max_length=200)


# ---------- 購入者 ----------


@app.get("/api/event")
def get_event(svc: Svc, response: Response) -> dict:
    _cache(response, 30)
    return svc.event().public(svc.clock())


@app.get("/api/event/seats")
def get_seats(svc: Svc, response: Response) -> dict:
    _cache(response, 3)  # CloudFront で数秒キャッシュして発売直後の負荷を吸収
    return svc.seat_status()


@app.post("/api/coupons/validate")
def validate_coupon(body: CouponBody, svc: Svc) -> dict:
    return {"valid": svc.coupon_exists(body.code)}


@app.post("/api/checkout")
def checkout(body: CheckoutBody, svc: Svc) -> dict:
    return svc.checkout(body.seat_ids, body.coupon_code, body.name, body.email)


@app.post("/api/checkout/cancel", status_code=204)
def cancel_checkout(body: SessionBody, svc: Svc) -> None:
    svc.cancel_checkout(body.session_id)


@app.get("/api/orders/by-session/{session_id}")
def order_by_session(session_id: str, svc: Svc) -> dict:
    return svc.order_by_session(session_id)


@app.get("/api/orders/{order_id}")
def order_by_key(order_id: str, svc: Svc, key: str = "") -> dict:
    return svc.order_by_key(order_id, key)


@app.get("/api/tickets/{token}")
def get_ticket(token: str, svc: Svc) -> dict:
    return svc.ticket(token)


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, svc: Svc) -> dict:
    payload = await request.body()
    try:
        svc.payments.verify_webhook(payload, request.headers.get("stripe-signature"))
    except Exception as e:
        raise ApiError(400, "bad_signature", "invalid signature") from e
    svc.handle_webhook(json.loads(payload))
    return {"received": True}


# ---------- スタッフ ----------


@app.post("/api/staff/checkin", dependencies=[Staff])
def staff_checkin(body: TokenBody, svc: Svc) -> dict:
    return svc.checkin(body.token.strip())


@app.get("/api/staff/orders", dependencies=[Staff])
def staff_search(svc: Svc, q: str = "") -> list[dict]:
    return svc.search_orders(q[:100])


@app.post("/api/staff/orders/{order_id}/checkin", status_code=204, dependencies=[Staff])
def staff_checkin_order(order_id: str, svc: Svc) -> None:
    svc.checkin_order(order_id)


@app.post("/api/staff/boxoffice", dependencies=[Staff])
def box_office(body: BoxOfficeBody, svc: Svc) -> dict:
    return svc.box_office(body.seat_ids, body.coupon_count)


# ---------- 管理者 ----------


@app.post("/api/admin/login")
def admin_login(body: LoginBody) -> dict:
    from app.config import get_secrets

    if not auth.verify_password(body.password, get_secrets().get("admin_password_hash")):
        raise ApiError(401, "unauthorized", "パスワードが違います")
    return {"token": auth.issue_admin_token()}


@app.get("/api/admin/summary", dependencies=[Admin])
def admin_summary(svc: Svc) -> dict:
    return svc.summary()


@app.get("/api/admin/orders", dependencies=[Admin])
def admin_orders(svc: Svc) -> list[dict]:
    return svc.admin_orders()


@app.get("/api/admin/orders.csv", dependencies=[Admin])
def admin_csv(svc: Svc) -> Response:
    return Response(
        svc.orders_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="orders.csv"'},
    )


@app.post("/api/admin/orders/{order_id}/resend", status_code=204, dependencies=[Admin])
def admin_resend(order_id: str, svc: Svc) -> None:
    svc.resend(order_id)


# ---------- Lambda ----------

_asgi = Mangum(app, lifespan="off")


def handler(event: dict, context: Any) -> Any:
    if event.get("task") == "sweep":  # EventBridge の定期実行
        result = get_service().sweep()
        log.info("sweep %s", result)
        return result
    return _asgi(event, context)
