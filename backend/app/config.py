"""設定と秘密情報。

秘密情報は SSM パラメータストア（`SSM_PREFIX` 配下、SecureString）から読む。
`SSM_PREFIX` が未設定のローカル開発時は同名の環境変数（大文字）を使う。
"""

import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache

SECRET_NAMES = ("stripe_secret_key", "stripe_webhook_secret", "staff_key", "admin_password_hash", "jwt_secret")


@dataclass(frozen=True)
class Settings:
    table_name: str
    event_id: str
    site_url: str  # 例: https://tickets.example.jp（末尾スラッシュなし）
    mail_from: str
    ssm_prefix: str | None
    # 仮押さえの期限。Stripe 側はこれより1分早く切れる。Stripe の expires_at は作成から30分以上が必要
    hold_minutes: int = 32


@lru_cache
def get_settings() -> Settings:
    return Settings(
        table_name=os.environ.get("TABLE_NAME", "teket-alt"),
        event_id=os.environ.get("EVENT_ID", "evt_2027"),
        site_url=os.environ.get("SITE_URL", "http://localhost:5173").rstrip("/"),
        mail_from=os.environ.get("MAIL_FROM", "tickets@example.com"),
        ssm_prefix=os.environ.get("SSM_PREFIX") or None,
    )


class Secrets:
    """SSM から一括取得して短時間キャッシュする（キーのローテーションを数十秒で反映）。"""

    TTL = 60.0

    def __init__(self, prefix: str | None):
        self._prefix = prefix.rstrip("/") if prefix else None
        self._cache: dict[str, str] = {}
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def get(self, name: str) -> str:
        if self._prefix is None:
            value = os.environ.get(name.upper(), "")
        else:
            with self._lock:
                if time.monotonic() - self._loaded_at > self.TTL:
                    self._cache = self._load()
                    self._loaded_at = time.monotonic()
            value = self._cache.get(name, "")
        if not value:
            raise RuntimeError(f"secret {name} is not configured")
        return value

    def _load(self) -> dict[str, str]:
        import boto3

        ssm = boto3.client("ssm")
        names = [f"{self._prefix}/{n}" for n in SECRET_NAMES]
        res = ssm.get_parameters(Names=names, WithDecryption=True)
        return {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in res["Parameters"]}


@lru_cache
def get_secrets() -> Secrets:
    return Secrets(get_settings().ssm_prefix)
