import pytest

from models.up_models import UpWebhook
from webhooks import WebhookPlan, plan_webhook_changes

W = "https://test.example.com/webhook"
H2 = "https://other.example.com"
V1 = "An automatic webhook to transfer data from Up into YNAB"
V2 = "UP to YNAB transaction sync webhook"


def hook(id, url, description=V2):
    return UpWebhook(id=id, url=url, description=description)


CASES = [
    ("none registered", [], W, (True, [], 0)),
    ("exact match", [hook("a", W)], W, (False, [], 0)),
    (
        "case and trailing slash variant",
        [hook("a", "HTTPS://Test.Example.com/webhook/")],
        W,
        (False, [], 0),
    ),
    ("duplicate deleted", [hook("a", W), hook("b", W)], W, (False, ["b"], 0)),
    (
        "foreign duplicate left",
        [hook("a", W), hook("b", W, None)],
        W,
        (False, [], 0),
    ),
    (
        "same-host v1 root hook deleted",
        [hook("old", "https://test.example.com/", V1), hook("a", W)],
        W,
        (False, ["old"], 0),
    ),
    (
        "other-host app hook warns",
        [hook("x", H2 + "/webhook")],
        W,
        (True, [], 1),
    ),
    (
        "foreign-description hook untouched",
        [hook("f", "https://test.example.com/", "Zapier")],
        W,
        (True, [], 0),
    ),
    (
        "live deployment",
        [
            hook("v1", "https://test.example.com/", V1),
            hook("a", W),
            hook("dup", W),
        ],
        W,
        (False, ["v1", "dup"], 0),
    ),
]


@pytest.mark.parametrize(
    "hooks,url,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_plan(hooks, url, expected):
    plan = plan_webhook_changes(hooks, url)

    assert (plan.create, plan.delete, len(plan.warnings)) == expected


@pytest.mark.parametrize("url", [None, "", "  "])
def test_unset_url_gives_empty_plan(url):
    assert plan_webhook_changes([hook("a", W)], url) == WebhookPlan()


def test_warning_names_hook():
    plan = plan_webhook_changes([hook("x", H2 + "/webhook")], W)

    assert plan.warnings == [
        f"Webhook x at {H2}/webhook is on another host; left in place"
    ]
