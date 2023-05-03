import os
from flask import Flask, request, Response
import classes
import helper

app = Flask(__name__)


@app.route("/", methods=["POST"])
def handle_up_webhook() -> Response:
    """
    Handles any webhook event from Up.
    """
    event_payload = classes.UpWebhookEvent(request.json["data"])
    outcome = helper.handleWebhookEvent(event_payload)

    print(outcome)

    return Response(status=200)


@app.route("/", methods=["GET"])
def refresh_databases() -> Response:
    """
    Refreshes databases.
    """
    helper.refresh()
    return Response(status=200)


if __name__ == "__main__":
    print("Starting server...")
    helper.setAllYNABDatabases()
    if not helper.pingWebhook():
        helper.createUpWebhook()
    print("Ready for transactions!")
    if helper.getEnvs("DEBUG_MODE") == "True":
        print("DEBUG MODE ENABLED")
    app.run(host="0.0.0.0", port=os.environ.get("PORT"))
