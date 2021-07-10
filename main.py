from flask import Flask, request, Response
import classes
import helper
import os

app = Flask(__name__)


@app.route("/up_webhook", methods=["POST"])
def respond():
    eventPayload = classes.UpWebhookEvent(request.json["data"])
    outcome = helper.handleWebhookEvent(eventPayload)

    print(outcome)

    return Response(status=200)


# endpoint to refresh the databases
@app.route("/refresh", methods=["GET"])
def refresh():
    helper.refresh()
    return Response(status=200)


if __name__ == "__main__":
    helper.setAllYNABDatabases()
    if not helper.pingWebhook():
        helper.createUpWebhook()
    app.run(host="0.0.0.0", port=os.environ.get("PORT"))
