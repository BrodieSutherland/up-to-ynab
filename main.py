from flask import Flask, request, Response
import classes
import helper

app = Flask(__name__)

@app.route('/upTransactions', methods=['POST'])
def respond():
    eventPayload = classes.UpWebhookEvent(request.json)
    helper.handleWebhookEvent(eventPayload)

    return Response(status=200)

if(__name__ == "__main__"):
    helper.setAllYNABDatabases()
    helper.createUpWebhook()
    app.run()