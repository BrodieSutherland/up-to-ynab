import pytest

from models.up_models import UpWebhook
from webhooks import WebhookPlan, plan_webhook_changes, sign, signature_valid

W = "https://test.example.com/webhook"
H2 = "https://other.example.com"
V1 = "An automatic webhook to transfer data from Up into YNAB"
V2 = "UP to YNAB transaction sync webhook"


def hook(id, url, description=V2):
    return UpWebhook(id=id, url=url, description=description)


CASES = [
    ("none registered", [], W, set(), (True, [], 0)),
    ("exact match", [hook("a", W)], W, {"a"}, (False, [], 0)),
    (
        "case and trailing slash variant",
        [hook("a", "HTTPS://Test.Example.com/webhook/")],
        W,
        {"a"},
        (False, [], 0),
    ),
    (
        "duplicate deleted",
        [hook("a", W), hook("b", W)],
        W,
        {"a", "b"},
        (False, ["b"], 0),
    ),
    (
        "foreign duplicate left",
        [hook("a", W), hook("b", W, None)],
        W,
        {"a"},
        (False, [], 1),
    ),
    (
        "same-host v1 root hook deleted",
        [hook("old", "https://test.example.com/", V1), hook("a", W)],
        W,
        {"a"},
        (False, ["old"], 0),
    ),
    (
        "other-host app hook warns",
        [hook("x", H2 + "/webhook")],
        W,
        set(),
        (True, [], 1),
    ),
    (
        "foreign-description hook untouched",
        [hook("f", "https://test.example.com/", "Zapier")],
        W,
        set(),
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
        {"a", "dup"},
        (False, ["v1", "dup"], 0),
    ),
    (
        "kept hook without secret is replaced",
        [hook("a", W)],
        W,
        set(),
        (True, ["a"], 0),
    ),
    (
        "later duplicate with secret is kept, first deleted",
        [hook("a", W), hook("b", W)],
        W,
        {"b"},
        (False, ["a"], 0),
    ),
    (
        "foreign hook at url without secret warns and creates",
        [hook("f", W, "Zapier")],
        W,
        set(),
        (True, [], 1),
    ),
]


@pytest.mark.parametrize(
    "hooks,url,known,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_plan(hooks, url, known, expected):
    plan = plan_webhook_changes(hooks, url, known_secret_ids=known)

    assert (plan.create, plan.delete, len(plan.warnings)) == expected


@pytest.mark.parametrize("url", [None, "", "  "])
def test_unset_url_gives_empty_plan(url):
    plan = plan_webhook_changes([hook("a", W)], url, known_secret_ids={"gone"})

    assert plan == WebhookPlan()


def test_warning_names_hook():
    plan = plan_webhook_changes([hook("x", H2 + "/webhook")], W, known_secret_ids=set())

    assert plan.warnings == [
        f"Webhook x at {H2}/webhook is on another host; left in place"
    ]


def test_stored_secrets_of_unlisted_hooks_are_forgotten():
    plan = plan_webhook_changes(
        [hook("a", W)], W, known_secret_ids={"a", "gone", "alsogone"}
    )

    assert plan.forget == ["alsogone", "gone"]


BODY = b'{"data":{"id":"evt-1"}}'
SIGNATURE = "7f06d0eceb5091977a5d07a97ecbe99ea4eab38c3b193fb17023bbf2cea4b7ed"


def test_sign_matches_a_known_hmac():
    assert sign(BODY, "test-secret") == SIGNATURE


@pytest.mark.parametrize(
    "signature,secrets,expected",
    [
        (SIGNATURE, ["test-secret"], True),
        (SIGNATURE.upper(), ["test-secret"], True),
        (f"  {SIGNATURE} ", ["test-secret"], True),
        (SIGNATURE, ["other", "test-secret"], True),
        (None, ["test-secret"], False),
        ("", ["test-secret"], False),
        ("  ", ["test-secret"], False),
        (SIGNATURE, ["other"], False),
        (SIGNATURE, [], False),
        ("caf\u00e9", ["test-secret"], False),
        (SIGNATURE[:-1] + "0", ["test-secret"], False),
    ],
)
def test_signature_valid(signature, secrets, expected):
    assert signature_valid(BODY, signature, secrets) is expected


def test_signature_is_bound_to_the_body():
    assert signature_valid(BODY + b" ", SIGNATURE, ["test-secret"]) is False
