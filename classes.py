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
        self.date = attributes["createdAt"]
        self.accountId = payload["relationships"]["account"]["data"]["id"]
        if payload["relationships"]["transferAccount"]["data"]:
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
        response = requests.get(helper.UP_BASE_URL + "transactions/" + self.transactionId, headers=helper.setHeaders("up"))

        if response.status_code == 200:
            self.transaction = UpTransaction(response.json()["data"])
        else:
            raise RuntimeError("Couldn't retrieve Up Transaction. Code: " + str(response.status_code) + "\nError: " + response.reason)

    def convertTransaction(self):
        pass

class YNABTransaction:
    def __init__(self, payload=None, transaction=None):
        if(payload != None):
            self.accountId = payload["account_id"]
            self.date = payload["date"]
            self.amount = payload["amount"]
            self.payeeId = payload["payee_id"]
            self.payeeName = payload["payee_name"]
            self.memo = payload["memo"]
        elif(transaction != None):
            self.accountId = transaction.accountId
            self.date = transaction.date
            self.amount = transaction.value
            self.payeeName = transaction.payee
            self.memo = transaction.message
