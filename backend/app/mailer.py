"""チケットメール。QR画像を CID でインライン添付し、SES の raw 送信で送る。"""

import html
import io
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from functools import lru_cache
from typing import Protocol

import boto3
import segno


@dataclass(frozen=True)
class MailTicket:
    url: str
    seat_label: str
    category_name: str


@dataclass(frozen=True)
class TicketMail:
    to: str
    holder_name: str
    event_name: str
    starts_at_jst: str
    doors_open_jst: str
    venue: str
    tickets: list[MailTicket]


def qr_png(data: str) -> bytes:
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=2)
    return buf.getvalue()


def build_message(mail: TicketMail, mail_from: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"【チケット】{mail.event_name}"
    msg["From"] = mail_from
    msg["To"] = mail.to

    e = html.escape
    text_lines = [
        f"{mail.holder_name} 様",
        "",
        "チケットのご購入ありがとうございます。当日は各チケットのQRコードを受付でご提示ください。",
        "",
        f"公演: {mail.event_name}",
        f"日時: {mail.starts_at_jst}（開場 {mail.doors_open_jst}）",
        f"会場: {mail.venue}",
        "",
    ]
    for t in mail.tickets:
        text_lines += [f"■ {t.category_name} {t.seat_label}", t.url, ""]
    text_lines.append("※ このメールに心当たりがない場合は破棄してください。")
    msg.set_content("\n".join(text_lines))

    cids = [make_msgid(domain="ticket") for _ in mail.tickets]
    blocks = "".join(
        f'<div style="border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 0;text-align:center">'
        f"<div><b>{e(t.category_name)}</b> {e(t.seat_label)}</div>"
        f'<img src="cid:{cid[1:-1]}" width="240" height="240" alt="QRコード">'
        f'<div><a href="{e(t.url)}">チケットを開く</a></div></div>'
        for t, cid in zip(mail.tickets, cids, strict=True)
    )
    body = (
        f"<p>{e(mail.holder_name)} 様</p>"
        "<p>チケットのご購入ありがとうございます。当日は各チケットのQRコードを受付でご提示ください。</p>"
        f"<p>公演: {e(mail.event_name)}<br>日時: {e(mail.starts_at_jst)}（開場 {e(mail.doors_open_jst)}）"
        f"<br>会場: {e(mail.venue)}</p>{blocks}"
        "<p style='color:#888;font-size:12px'>※ このメールに心当たりがない場合は破棄してください。</p>"
    )
    msg.add_alternative(f"<html><body>{body}</body></html>", subtype="html")
    html_part = msg.get_body(preferencelist=("html",))
    assert isinstance(html_part, EmailMessage)
    for t, cid in zip(mail.tickets, cids, strict=True):
        html_part.add_related(qr_png(t.url), maintype="image", subtype="png", cid=cid, filename="qr.png")
    return msg


class Mailer(Protocol):
    def send(self, mail: TicketMail) -> None: ...


class SesMailer:
    def __init__(self, mail_from: str):
        self.mail_from = mail_from

    def send(self, mail: TicketMail) -> None:
        raw = build_message(mail, self.mail_from).as_bytes()
        boto3.client("sesv2").send_email(
            FromEmailAddress=self.mail_from,
            Destination={"ToAddresses": [mail.to]},
            Content={"Raw": {"Data": raw}},
        )


@lru_cache
def get_mailer() -> Mailer:
    from app.config import get_settings

    return SesMailer(get_settings().mail_from)
