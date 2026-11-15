"""スタッフ（受付URLのキー）と管理者（パスワード → JWT）の認証。"""

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt

from app.config import get_secrets
from app.db import now

JWT_TTL = timedelta(hours=12)
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    b64 = base64.urlsafe_b64encode
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt).decode()}${b64(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(dk)
        got = hashlib.scrypt(
            password.encode(), salt=base64.urlsafe_b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(got, expected)


def verify_staff_key(key: str | None) -> bool:
    if not key:
        return False
    # ローテーション中は旧キーと新キーをカンマ区切りで併記できる
    keys = [k.strip() for k in get_secrets().get("staff_key").split(",") if k.strip()]
    return any(hmac.compare_digest(key.encode(), k.encode()) for k in keys)


def issue_admin_token() -> str:
    t = now()
    return jwt.encode(
        {"sub": "admin", "iat": int(t.timestamp()), "exp": int((t + JWT_TTL).timestamp())},
        get_secrets().get("jwt_secret"),
        algorithm="HS256",
    )


def verify_admin_token(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    try:
        claims = jwt.decode(authorization[7:], get_secrets().get("jwt_secret"), algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return claims.get("sub") == "admin"
