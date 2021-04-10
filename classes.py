import requests
import helper
import shelve

# UP API CLASSES
class UpTransaction:
    def __init__(self, payload):
        print(payload)
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
        if payload["relationships"]["category"]["data"]:
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
        if self.transaction:
            self.ynabTransaction = YNABTransaction(transaction=self.transaction)
        else:
            print("There is currently no transaction against this Event")

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
            upAcc = shelve.open("databases/up_accounts")
            ynabAcc = shelve.open("databases/accounts__name")

            self.accountId = ynabAcc[upAcc[transaction.accountId]]
            
            upAcc.close()
            ynabAcc.close()
            
            self.date = transaction.date
            self.amount = transaction.value
            self.payeeName = transaction.payee
            self.memo = transaction.message

            payeeNames = shelve.open("databases/payees__name")
            try:
                self.payeeId = payeeNames[self.payeeName]
            except Exception:
                print("new payee")
            payeeNames.close()
