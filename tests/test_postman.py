import json
import re
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Route

from app import create_app
from models.up_models import UpWebhook
from tests.fakes.up import FakeUpClient
from tests.fakes.webhook_secrets import InMemoryWebhookSecretStore
from tests.test_api_endpoints import make_services
from webhooks import SIGNATURE_HEADER, sign, signature_valid

POSTMAN = Path(__file__).parent.parent / "docs" / "postman"
COLLECTION_FILE = POSTMAN / "up-to-ynab.postman_collection.json"
ENVIRONMENT_FILE = POSTMAN / "up-to-ynab.postman_environment.json"

SECRET = "postman-test-secret"
BODY = (
    b'{"data":{"type":"webhook-events","id":"postman-ping","attributes":'
    b'{"eventType":"PING","createdAt":"2026-10-30T09:00:00+11:00"}}}'
)
BODY_SIGNATURE = "8262c5f1bcee8e4782964b1bfd047b42cff764d27cf3d4d753b350140cd36aee"


def collection():
    return json.loads(COLLECTION_FILE.read_text())


def environment():
    return json.loads(ENVIRONMENT_FILE.read_text())


def requests(items, path=()):
    """Yield (folder path, item) for every request in the collection."""
    for item in items:
        if "item" in item:
            yield from requests(item["item"], path + (item["name"],))
        else:
            yield path, item


def find_folder(items, name):
    for item in items:
        if item["name"] == name:
            return item
        if "item" in item:
            found = find_folder(item["item"], name)
            if found:
                return found
    return None


def resolve(text):
    return text.replace("{{upWebhookId}}", "hook-1").replace(
        "{{upTransactionId}}", "tx-1"
    )


def test_collection_shape():
    col = collection()
    assert (
        col["info"]["schema"]
        == "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
    )
    assert col["info"]["name"]
    assert [f["name"] for f in col["item"]] == [
        "App",
        "Webhook",
        "Up API",
        "YNAB API",
    ]

    def walk(items):
        for item in items:
            assert item["name"]
            assert ("item" in item) != ("request" in item)
            if "item" in item:
                assert isinstance(item["item"], list)
                walk(item["item"])
            else:
                assert item["request"]["method"]
                assert item["request"]["url"]["raw"]

    walk(col["item"])


def test_environment_variables():
    env = environment()
    assert env["_postman_variable_scope"] == "environment"
    by_key = {v["key"]: v for v in env["values"]}
    assert set(by_key) == {
        "baseUrl",
        "adminToken",
        "webhookSecret",
        "upToken",
        "ynabToken",
        "budgetId",
        "upTransactionId",
        "upWebhookId",
        "ynabTransactionId",
    }
    assert by_key["baseUrl"]["value"] == "http://localhost:5001"
    for key in ("adminToken", "webhookSecret", "upToken", "ynabToken"):
        assert by_key[key]["type"] == "secret"
        assert by_key[key]["value"] == ""


def test_app_requests_match_real_routes(test_settings):
    routes = create_app(test_settings).routes
    found = set()
    for _, item in requests(collection()["item"]):
        raw = item["request"]["url"]["raw"]
        if not raw.startswith("{{baseUrl}}"):
            continue
        path = re.sub(
            r"\{\{\w+\}\}", "x", raw.removeprefix("{{baseUrl}}").split("?")[0]
        )
        method = item["request"]["method"]
        assert any(
            isinstance(r, (APIRoute, Route))
            and method in (r.methods or ())
            and r.path_regex.match(path)
            for r in routes
        ), (method, path)
        found.add((method, path))
    assert found == {
        ("GET", "/health"),
        ("GET", "/refresh"),
        ("POST", "/backfill"),
        ("GET", "/ledger/x"),
        ("GET", "/docs"),
        ("POST", "/webhook"),
    }


def test_signing_script_and_bodies():
    col = collection()
    signed = find_folder(col["item"], "Signed events")
    script = "\n".join(signed["event"][0]["script"]["exec"])
    assert "CryptoJS.HmacSHA256(body, secret)" in script
    assert "CryptoJS.enc.Hex" in script
    assert "pm.variables.replaceIn(pm.request.body.raw)" in script
    assert SIGNATURE_HEADER in script

    webhook = find_folder(col["item"], "Webhook")
    unsigned = next(i for i in webhook["item"] if "request" in i)
    assert "event" not in unsigned
    assert SIGNATURE_HEADER not in json.dumps(unsigned)

    names = []
    for _, item in requests(signed["item"]):
        body = json.loads(resolve(item["request"]["body"]["raw"]))
        assert body["data"]["attributes"]["eventType"] == item["name"]
        names.append(item["name"])
    assert names == [
        "TRANSACTION_CREATED",
        "TRANSACTION_SETTLED",
        "TRANSACTION_DELETED",
        "PING",
    ]


def test_signature_matches_the_app():
    assert sign(BODY, SECRET) == BODY_SIGNATURE
    assert signature_valid(BODY, BODY_SIGNATURE, [SECRET])


def test_unsigned_and_signed_requests_against_the_app(test_settings):
    col = collection()
    webhook = find_folder(col["item"], "Webhook")
    unsigned = next(i for i in webhook["item"] if "request" in i)
    body = resolve(unsigned["request"]["body"]["raw"]).encode()
    up = FakeUpClient(
        webhooks=[UpWebhook(id="postman-hook", url=test_settings.webhook_url)]
    )
    secrets = InMemoryWebhookSecretStore({"postman-hook": SECRET})
    app = create_app(test_settings, make_services(up, secrets=secrets))
    headers = {"Content-Type": "application/json"}
    with TestClient(app) as client:
        assert client.post("/webhook", content=body, headers=headers).status_code == 401
        headers[SIGNATURE_HEADER] = sign(body, SECRET)
        response = client.post("/webhook", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_no_secrets_in_files():
    for path in (COLLECTION_FILE, ENVIRONMENT_FILE):
        text = path.read_text()
        assert "up:yeah:" not in text
        assert not re.search(r"[0-9a-fA-F]{40,}", text)
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            text,
            re.IGNORECASE,
        )
        assert not re.search(r"Bearer (?!\{\{)", text)
