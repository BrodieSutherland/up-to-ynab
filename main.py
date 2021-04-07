from flask import Flask, request, Response
import classes
import helper
import os
from run import app as application

app = Flask(__name__)

@app.route('/up_webhook', methods=['POST'])
def respond():
    eventPayload = classes.UpWebhookEvent(request.json)
    helper.handleWebhookEvent(eventPayload)

    return Response(status=200)

if(__name__ == "__main__"):
    helper.setAllYNABDatabases()
    # helper.createUpWebhook()
    port = os.environ.get('PORT')
    application.run(host='0.0.0.0', port=os.environ.get("PORT"))