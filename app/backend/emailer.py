"""Emergent-managed email (Resend proxy) — weekly digest of top headcount movers."""
import os
import re
import ipaddress
import logging
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "DisruptRadar")

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "send your password", "cvv", "seed phrase",
             "social security number", "confirm your card number", "recovery phrase")


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls = set(), []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms/inputs in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Links must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Unsafe URL: {url!r} (G3)")


async def send_email(to: str, subject: str, html: str) -> str | None:
    if not EMAIL_KEY:
        logger.warning("EMERGENT_EMAIL_KEY missing — email send skipped")
        return None
    _assert_safe_email(subject, html)
    payload = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{EMAIL_BASE_URL}/api/v1/email/send",
            headers={"X-Email-Key": EMAIL_KEY}, json=payload,
        )
    resp.raise_for_status()
    return resp.json().get("id")


def build_digest_html(workspace_name: str, movers: list[dict]) -> str:
    rows = ""
    for m in movers:
        color = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981"}.get(m.get("risk"), "#94a3b8")
        delta = m.get("delta_pct")
        delta_s = f"{delta:+.1f}%" if delta is not None else "—"
        rows += (
            f'<tr><td style="padding:10px 8px;border-bottom:1px solid #1E2436;color:#F8FAFC;font-weight:600">{escape(m["domain"])}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #1E2436;color:#94A3B8;text-align:right">{m.get("headcount") or "—"}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #1E2436;text-align:right;color:{color};font-weight:600">{delta_s}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #1E2436;text-align:right"><span style="color:{color};font-weight:700;font-size:12px">{escape(str(m.get("risk") or "—"))}</span></td></tr>'
        )
    if not rows:
        rows = '<tr><td colspan="4" style="padding:16px;color:#94A3B8;text-align:center">No movements this week.</td></tr>'
    return (
        f'<table role="presentation" width="100%" style="max-width:560px;margin:0 auto;background:#10131E;border:1px solid #1E2436;border-radius:12px;font-family:Arial,Helvetica,sans-serif">'
        f'<tr><td style="padding:24px">'
        f'<p style="color:#3B82F6;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 4px">Weekly Intelligence Digest</p>'
        f'<h1 style="color:#F8FAFC;font-size:22px;margin:0 0 4px">{escape(workspace_name)}</h1>'
        f'<p style="color:#94A3B8;font-size:14px;margin:0 0 20px">Top headcount movers across your watchlist this week.</p>'
        f'<table role="presentation" width="100%" style="border-collapse:collapse">'
        f'<tr><th style="text-align:left;padding:8px;color:#64748B;font-size:11px;text-transform:uppercase">Domain</th>'
        f'<th style="text-align:right;padding:8px;color:#64748B;font-size:11px;text-transform:uppercase">Headcount</th>'
        f'<th style="text-align:right;padding:8px;color:#64748B;font-size:11px;text-transform:uppercase">Delta</th>'
        f'<th style="text-align:right;padding:8px;color:#64748B;font-size:11px;text-transform:uppercase">Risk</th></tr>'
        f'{rows}</table>'
        f'<p style="color:#64748B;font-size:12px;margin:20px 0 0">Sent by {escape(EMAIL_FROM_NAME)}. We never ask for your password or payment details by email.</p>'
        f'</td></tr></table>'
    )