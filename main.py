from flask import Flask, request, Response
import classes
import helper
import os

app = Flask(__name__)


# ---------------
# ROUTES
# ---------------
# Endpoint to handle updates from Up
@app.route("/up_webhook", methods=["POST"])
def respond() -> Response:
    """Handles any webhook event from Up"""
    eventPayload = classes.UpWebhookEvent(request.json["data"])
    outcome = helper.handleWebhookEvent(eventPayload)

    print(outcome)

    return Response(status=200)


# Endpoint to refresh peyee databases
@app.route("/refresh", methods=["GET"])
def refresh() -> Response:
    """Refreshes databases"""
    helper.refresh()
    return Response(status=200)


if __name__ == "__main__":
    helper.setAllYNABDatabases()
    if not helper.pingWebhook():
        helper.createUpWebhook()
    app.run(host="0.0.0.0", port=os.environ.get("PORT"))
