from flask import Flask, request, Response
import classes
import helper
import os

app = Flask(__name__)

@app.route('/up_webhook', methods=['POST'])
def respond():
    eventPayload = classes.UpWebhookEvent(request.json)
    helper.handleWebhookEvent(eventPayload)

    return Response(status=200)

if(__name__ == "__main__"):
    helper.setAllYNABDatabases()
    helper.createUpWebhook()
    app.run(port=os.environ.get("PORT"))