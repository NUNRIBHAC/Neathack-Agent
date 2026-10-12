"""Dodo Payments hosted checkout: Free -> Pro. Credentials stay server-side."""
import os
import json
import logging

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("DODO_PAYMENTS_API_KEY", "")
ENVIRONMENT = os.environ.get("DODO_PAYMENTS_ENVIRONMENT", "test_mode")
WEBHOOK_KEY = os.environ.get("DODO_PAYMENTS_WEBHOOK_KEY", "")
PRO_PRODUCT_ID = os.environ.get("DODO_PRO_PRODUCT_ID", "")

_async_client = None
_webhook_client = None


def _clients():
    global _async_client, _webhook_client
    if _async_client is None:
        from dodopayments import AsyncDodoPayments, DodoPayments
        _async_client = AsyncDodoPayments(bearer_token=API_KEY, environment=ENVIRONMENT)
        _webhook_client = DodoPayments(bearer_token=API_KEY, environment=ENVIRONMENT, webhook_key=WEBHOOK_KEY)
    return _async_client, _webhook_client


def is_configured() -> bool:
    return bool(API_KEY and PRO_PRODUCT_ID)


async def create_checkout(workspace_id: str, return_url: str) -> dict:
    if not is_configured():
        raise RuntimeError("Dodo Pro product not configured (set DODO_PRO_PRODUCT_ID)")
    client, _ = _clients()
    session = await client.checkout_sessions.create(
        product_cart=[{"product_id": PRO_PRODUCT_ID, "quantity": 1}],
        metadata={"workspace_id": workspace_id},
        return_url=return_url,
    )
    return {"session_id": getattr(session, "session_id", None), "checkout_url": getattr(session, "checkout_url", None)}


def verify_webhook(raw: bytes, headers: dict):
    """Returns parsed payload dict if signature valid, else raises."""
    _, webhook_client = _clients()
    webhook_client.webhooks.unwrap(raw, headers=headers)
    return json.loads(raw)