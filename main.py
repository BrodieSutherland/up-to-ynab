from flask import Flask, request, Response
import classes
import helper
import os

app = Flask(__name__)

@app.route('/up_webhook', methods=['POST'])
def respond():
    eventPayload = classes.UpWebhookEvent(request.json["data"])
    test = helper.handleWebhookEvent(eventPayload)

    # body = {
    #     "data" : test
    # }

    print(test)

    return Response(status=200)

if(__name__ == "__main__"):
    helper.setAllYNABDatabases()
    # helper.createUpWebhook()
    port = os.environ.get('PORT')
    app.run(host='0.0.0.0', port=port)