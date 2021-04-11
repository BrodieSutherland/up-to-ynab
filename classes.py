import requests
import helper
import shelve

# UP API CLASSES
class UpTransaction:
    def __init__(self, payload):
        self.id = payload["id"]
        attributes = payload["attributes"]
        self.status = attributes["status"]
        self.payee = attributes["description"]
        self.message = attributes["message"]
        self.value = float(attributes["amount"]["value"])
        self.date = attributes["createdAt"]
        self.accountId = payload["relationships"]["account"]["data"]["id"]

        accounts = shelve.open("databases/up_accounts")
        self.accountName = accounts[self.accountId]
        accounts.close()

        if payload["relationships"]["transferAccount"]["data"]:
            self.transferAccountId = payload["relationships"]["transferAccount"]["data"]["id"]
        if payload["relationships"]["category"]["data"]:
            self.category = payload["relationships"]["category"]["data"]["id"]

class UpAccount:
    def __init__(self, payload):
        self.id = payload["id"]
        self.name = payload["attributes"]["displayName"]
        self.type = payload["attributes"]["accountType"]

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
            self.ynabTransaction = YNABTransaction(upTransaction=self.transaction)
        else:
            print("There is currently no transaction against this Event")

# YNAB API CLASSES
class YNABBase:
    def __init__(self, payload):
        self.id = payload["id"]
        self.name = payload["name"]

class YNABTransaction(YNABBase):
    def __init__(self, jsonPayload=None, upTransaction=None):
        if(jsonPayload != None):
            self.accountId = jsonPayload["account_id"]
            self.date = jsonPayload["date"][0 : 10]
            self.amount = int(float(jsonPayload["amount"]))
            self.amount = self.amount * 1000
            self.payeeId = jsonPayload["payee_id"]
            self.categoryId = jsonPayload["category_id"]
            try:
                self.payeeName = jsonPayload["payee_name"]
            except:
                pass
            self.memo = jsonPayload["memo"]

        elif(upTransaction != None):
            ynabAcc = shelve.open("databases/accounts__name")

            self.accountId = ynabAcc[upTransaction.accountName].id
            
            ynabAcc.close()

            self.date = upTransaction.date[0 : 10]
            self.amount = int(upTransaction.value * 1000)
            if upTransaction.payee != "Round Up":
                self.payeeName = upTransaction.payee
            else:
                self.payeeName = None
            self.memo = upTransaction.message

            payeeToCat = shelve.open("databases/payeeToCategories")

            try:
                self.categories = list(payeeToCat[self.payeeName])
            except:
                self.categories = []

            payeeToCat.close()

    def setPayeeName(self):
        database = shelve.open("databases/payees__id")
        self.payeeName = database[self.payeeId].name
        database.close()

class YNABAccount(YNABBase):
    def __init__(self, payload):
        YNABBase.__init__(self, payload)
        self.transferId = payload["transfer_payee_id"]

class YNABPayee(YNABBase):
    def __init__(self, payload):
        YNABBase.__init__(self, payload)

class YNABCategory(YNABBase):
    def __init__(self, payload):
        YNABBase.__init__(self, payload)

class YNABCategoryGroup(YNABBase):
    def __init__(self, payload):
        YNABBase.__init__(self, payload)

class YNABBudget(YNABBase):
    def __init__(self, payload):
        YNABBase.__init__(self, payload)

        self.accounts = []
        for acc in payload["accounts"]:
            self.accounts.append(YNABAccount(acc))
        
        self.categories = []
        for cat in payload["categories"]:
            self.categories.append(YNABCategory(cat))
        
        self.categoryGroups = []
        for catGroup in payload["category_groups"]:
            self.categoryGroups.append(YNABCategoryGroup(catGroup))
        
        self.payees = []
        for pay in payload["payees"]:
            self.payees.append(YNABPayee(pay))

        self.transactions = []
        for transaction in payload["transactions"]:
            self.transactions.append(YNABTransaction(jsonPayload=transaction))

    def setAccountDatabase(self):
        helper.setDatabase("accounts", self.accounts, "id")
        helper.setDatabase("accounts", self.accounts, "name")

    def setPayeeDatabase(self):
        helper.setDatabase("payees", self.payees, "id")
        helper.setDatabase("payees", self.payees, "name")

        payeeToCategories = shelve.open("databases/payeeToCategories")
        categories = shelve.open("databases/categories__id")

        for transaction in self.transactions:
            transaction.setPayeeName()
            try:
                payeeToCategories[transaction.payeeName].add(categories[transaction.categoryId])
            except:
                if "Transfer :" not in transaction.payeeName and transaction.categoryId != None:
                    payeeToCategories[transaction.payeeName] = set([categories[transaction.categoryId]])

        categories.close()
        payeeToCategories.close()

    def setCategoryGroupDatabase(self):
        helper.setDatabase("category_groups", self.categoryGroups, "id")
        helper.setDatabase("category_groups", self.categoryGroups, "name")

    def setCategoryDatabase(self):
        helper.setDatabase("category", self.categories, "id")
        helper.setDatabase("category", self.categories, "name")