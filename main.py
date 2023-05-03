from flask import Flask, request, Response
import classes
import helper
import os

app = Flask(__name__)

# ---------------
# ROUTES
# ---------------
# Endpoint to handle updates from Up
@app.route("/", methods=["POST", "GET"])
def respond() -> Response:
    if request.method == "POST":
        """Handles any webhook event from Up"""
        eventPayload = classes.UpWebhookEvent(request.json["data"])
        outcome = helper.handleWebhookEvent(eventPayload)

        app.logger.info(outcome)

        return Response(status=200)
    elif request.method == "GET":
        """Refreshes databases"""
        helper.refresh()
        return Response(status=200)

if __name__ == "__main__":
    app.logger.info("Starting server...")
    helper.setAllYNABDatabases()
    if not helper.pingWebhook():
        helper.createUpWebhook()
    app.logger.info("Ready for transactions!")
    if helper.getEnvs("DEBUG_MODE") == "True":
        app.logger.info("DEBUG MODE ENABLED")
    app.run(host="0.0.0.0", port=os.environ.get("PORT"))
