from dataclasses import dataclass, field
from typing import Sequence
from urllib.parse import urlsplit

from clients.up import WEBHOOK_DESCRIPTION
from models.up_models import UpWebhook

V1_WEBHOOK_DESCRIPTION = "An automatic webhook to transfer data from Up into YNAB"
APP_DESCRIPTIONS = frozenset({V1_WEBHOOK_DESCRIPTION, WEBHOOK_DESCRIPTION})


@dataclass(frozen=True)
class WebhookPlan:
    """What to change in Up so exactly one hook points at the webhook URL."""

    create: bool = False
    delete: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalise(url: str) -> tuple[str, str, str, str]:
    parts = urlsplit(url.strip())
    return (
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/"),
        parts.query,
    )


def plan_webhook_changes(
    registered_hooks: Sequence[UpWebhook], webhook_url: str | None
) -> WebhookPlan:
    """Decide which hooks to create and delete; pure, holds every rule.

    The first hook matching webhook_url is kept. Later exact duplicates and
    same-host hooks at another path are deleted only when they carry one of
    this app's descriptions. App-described hooks on other hosts only warn;
    hooks without an app description are never touched.
    """
    if not webhook_url or not webhook_url.strip():
        return WebhookPlan()
    target = _normalise(webhook_url)
    matched = False
    delete: list[str] = []
    warnings: list[str] = []
    for hook in registered_hooks:
        ours = hook.description in APP_DESCRIPTIONS
        normalised = _normalise(hook.url)
        if normalised == target:
            if not matched:
                matched = True
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
    return WebhookPlan(create=not matched, delete=delete, warnings=warnings)
