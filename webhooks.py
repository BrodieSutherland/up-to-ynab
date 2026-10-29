import hmac
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from typing import Sequence
from urllib.parse import urlsplit

from clients.up import WEBHOOK_DESCRIPTION
from models.up_models import UpWebhook

V1_WEBHOOK_DESCRIPTION = "An automatic webhook to transfer data from Up into YNAB"
APP_DESCRIPTIONS = frozenset({V1_WEBHOOK_DESCRIPTION, WEBHOOK_DESCRIPTION})
SIGNATURE_HEADER = "X-Up-Authenticity-Signature"


@dataclass(frozen=True)
class WebhookPlan:
    """What to change in Up so exactly one hook points at the webhook URL."""

    create: bool = False
    delete: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    forget: list[str] = field(default_factory=list)


def _normalise(url: str) -> tuple[str, str, str, str]:
    parts = urlsplit(url.strip())
    return (
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/"),
        parts.query,
    )


def plan_webhook_changes(
    registered_hooks: Sequence[UpWebhook],
    webhook_url: str | None,
    *,
    known_secret_ids: Collection[str],
) -> WebhookPlan:
    """Decide which hooks to create and delete; pure, holds every rule.

    The first hook at webhook_url whose secret is stored is kept. Other
    app-described hooks at that URL, and same-host app-described hooks at
    another path, are deleted. App-described hooks on other hosts only warn.
    Hooks without an app description are never touched; one at webhook_url
    without a stored secret cannot be used, so it is left and a new hook is
    created. Stored secrets of hooks Up no longer lists are forgotten.
    """
    if not webhook_url or not webhook_url.strip():
        return WebhookPlan()
    target = _normalise(webhook_url)
    kept = False
    delete: list[str] = []
    warnings: list[str] = []
    for hook in registered_hooks:
        ours = hook.description in APP_DESCRIPTIONS
        normalised = _normalise(hook.url)
        if normalised == target:
            if not ours:
                if hook.id not in known_secret_ids:
                    warnings.append(
                        f"Webhook {hook.id} at {hook.url} was not created by this "
                        "app and has no stored secret; left in place"
                    )
                    continue
            if not kept and hook.id in known_secret_ids:
                kept = True
            elif ours:
                delete.append(hook.id)
        elif ours:
            if normalised[1] == target[1]:
                delete.append(hook.id)
            else:
                warnings.append(
                    f"Webhook {hook.id} at {hook.url} is on another host; "
                    "left in place"
                )
    listed = {hook.id for hook in registered_hooks}
    return WebhookPlan(
        create=not kept,
        delete=delete,
        warnings=warnings,
        forget=sorted(set(known_secret_ids) - listed),
    )


def sign(body: bytes, secret: str) -> str:
    """The hex SHA-256 HMAC of a webhook body, as Up sends it."""
    return hmac.new(secret.encode(), body, "sha256").hexdigest()


def signature_valid(body: bytes, signature: str | None, secrets: Iterable[str]) -> bool:
    """True if signature is the HMAC of body under any of the secrets.

    Compares in constant time over bytes, so odd header values cannot raise.
    """
    if not signature or not signature.strip():
        return False
    received = signature.strip().lower().encode()
    valid = False
    for secret in secrets:
        if hmac.compare_digest(sign(body, secret).encode(), received):
            valid = True
    return valid
