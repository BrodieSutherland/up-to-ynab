import requests
import helper

# UP API CLASSES
class UpTransaction:
    def __init__(self, payload):
        self.id = payload["id"]
        attributes = payload["attributes"]
        self.status = attributes["status"]
        self.payee = attributes["description"]
        self.message = attributes["message"]
        self.value = attributes["amount"]["value"]
        self.settleDate = attributes["settledAt"]
        self.accountId = payload["relationships"]["account"]["data"]["id"]
        self.transferAccountId = payload["relationships"]["transferAccount"]["data"]["id"]
        self.category = payload["relationships"]["category"]["data"]["id"]

class UpWebhookEvent:
    def __init__(self, payload):
        self.id = payload["id"]
        self.type = payload["attributes"]["eventType"]
        self.date = payload["attributes"]["createdAt"]
        try:
            self.transactionId = payload["relationships"]["transaction"]["data"]["id"]
        except:
            print("Not a transaction?")

    def getTransaction(self):
        response = requests.get(helper.YNAB_BASE_URL + "transactions/" + self.transactionId, headers = helper.setHeaders("up"))

        if response.status_code == 200:
            return UpTransaction(response.json["data"])
        else:
            raise RuntimeError("Couldn't retrieve Up Transaction. Code: " + str(response.status_code) + "\nError: " + response.reason)
