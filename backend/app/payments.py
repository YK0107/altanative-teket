"""Stripe との境界。テストでは差し替える。"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import stripe

from app.config import get_secrets


@dataclass(frozen=True)
class SessionState:
    id: str
    status: str  # open / complete / expired
    payment_status: str  # paid / unpaid / no_payment_required
    amount_total: int | None
    order_id: str | None
    email: str | None = None  # 購入者のメール。DBには保存せず、送信時に Stripe から取得する


class Payments(Protocol):
    def create_session(
        self,
        *,
        order_id: str,
        amount: int,
        description: str,
        quantity: int,
        email: str,
        expires_at: int,
        success_url: str,
        cancel_url: str,
    ) -> tuple[str, str]: ...

    def retrieve(self, session_id: str) -> SessionState: ...

    def expire(self, session_id: str) -> SessionState: ...

    def verify_webhook(self, payload: bytes, signature: str | None) -> None: ...


def _state(s: Any) -> SessionState:
    md = s.metadata or {}
    email = (s.customer_details.email if s.customer_details else None) or s.customer_email
    return SessionState(s.id, s.status or "", s.payment_status or "", s.amount_total, md.get("order_id"), email)


class StripePayments:
    def _client(self) -> stripe.StripeClient:
        return stripe.StripeClient(get_secrets().get("stripe_secret_key"), max_network_retries=2)

    def create_session(
        self,
        *,
        order_id: str,
        amount: int,
        description: str,
        quantity: int,
        email: str,
        expires_at: int,
        success_url: str,
        cancel_url: str,
    ) -> tuple[str, str]:
        s = self._client().v1.checkout.sessions.create(
            params={
                "mode": "payment",
                "allowed_payment_method_types": ["card"],
                "locale": "ja",
                "customer_email": email,
                "expires_at": expires_at,
                "client_reference_id": order_id,
                "metadata": {"order_id": order_id},
                "payment_intent_data": {"metadata": {"order_id": order_id}},
                "line_items": [
                    {
                        "quantity": 1,
                        "price_data": {
                            "currency": "jpy",
                            "unit_amount": amount,
                            "product_data": {"name": f"チケット {quantity}枚", "description": description},
                        },
                    }
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
            },
            options={"idempotency_key": f"checkout-{order_id}"},
        )
        if not s.url:
            raise RuntimeError("Stripe session has no url")
        return s.id, s.url

    def retrieve(self, session_id: str) -> SessionState:
        return _state(self._client().v1.checkout.sessions.retrieve(session_id))

    def expire(self, session_id: str) -> SessionState:
        return _state(self._client().v1.checkout.sessions.expire(session_id))

    def verify_webhook(self, payload: bytes, signature: str | None) -> None:
        stripe.WebhookSignature.verify_header(payload, signature, get_secrets().get("stripe_webhook_secret"), 300)


@lru_cache
def get_payments() -> Payments:
    return StripePayments()
