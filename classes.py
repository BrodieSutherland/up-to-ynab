import requests
import helper
import shelve
import json

INTERNAL_TRANSFER_STRINGS = ["Transfer to ", "Quick save transfer from ", "Quick save transfer to "]

# UP API CLASSES
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

        try:
            response.raise_for_status()
            self.transaction = UpTransaction(response.json()["data"])
        except requests.exceptions.HTTPError as http_err:
            print("An HTTP Error has occurred.\nStatus Code: " + str(http_err.response.status_code) + "\nError: " + http_err.response.reason)

    def convertTransaction(self):
        if self.transaction:
            self.ynabTransaction = YNABTransaction(upTransaction=self.transaction)
        else:
            print("There is currently no transaction against this Event")

class UpTransaction:
    def __init__(self, payload):
        self.id = payload["id"]
        attributes = payload["attributes"]
        self.isInternal = True if attributes["rawText"] == None else False
        self.status = attributes["status"]
        self.payee = attributes["description"]
        self.message = attributes["message"]
        self.value = float(attributes["amount"]["value"])
        self.date = attributes["createdAt"]
        self.accountId = payload["relationships"]["account"]["data"]["id"]

        self.accountName = helper.setVariableFromShelf("databases/up_accounts", self.accountId).name

class UpAccount:
    def __init__(self, payload):
        self.id = payload["id"]
        self.name = payload["attributes"]["displayName"]
        self.type = payload["attributes"]["accountType"]

# YNAB API CLASSES
class YNABBase:
    def __init__(self, payload):
        self.id = payload["id"]
        self.name = payload["name"]

class YNABTransaction(YNABBase):
    def __init__(self, jsonPayload=None, upTransaction=None):
        if(jsonPayload != None):
            self.id = jsonPayload["id"]
            self.accountId = jsonPayload["account_id"]
            self.date = jsonPayload["date"][0 : 10]
            self.amount = int(float(jsonPayload["amount"])) * 1000
            self.categoryId = jsonPayload["category_id"]
            self.memo = jsonPayload["memo"]

            self.payeeId = jsonPayload["payee_id"]
            if "payee_name" in jsonPayload:
                self.payeeName = jsonPayload["payee_name"]
            else:
                self.payeeName = helper.setVariableFromShelf("databases/payees__id", self.payeeId).name

        elif(upTransaction != None):
            self.accountId = helper.setVariableFromShelf("databases/accounts__name", upTransaction.accountName).id

            self.date = upTransaction.date[0 : 10]
            self.amount = int(upTransaction.value * 1000)
            self.memo = upTransaction.message

            if upTransaction.payee == "Round Up":
                self.payeeName = None
                self.payeeId = helper.TRANSACTIONAL_ACCOUNT_ID
                self.categories = []
            elif upTransaction.isInternal:
                # Some wack shit in here because the transferId value in the Up Transaction payload doesn't work/is very rarely shown
                # so I've had to build some janky shit to get around it, keen to turf this ASAP

                accountName = upTransaction.payee.replace("Spending", "Up Account")
                for sub in INTERNAL_TRANSFER_STRINGS:
                    accountName = accountName.replace(sub, "")
                for account in helper.UP_ACCOUNTS:
                    if accountName in account:
                        self.payeeId = helper.setVariableFromShelf("databases/accounts__name", account).transferId
                self.categories = []
                self.payeeName = None
            else:
                self.payeeName = upTransaction.payee
                self.payeeId = helper.setVariableFromShelf("databases/payees__name", self.payeeName).id
                self.categories = list(helper.setVariableFromShelf("databases/payeeToCategories", self.payeeName))

    def sendNewYNABTransaction(self):
        body = {
            "transaction" : {
                "account_id" : self.accountId,
                "date" : self.date,
                "amount" : self.amount,
                "payee_name" : self.payeeName,
                "payee_id" : self.payeeId,
                "category_name" : self.categories[0].name if len(self.categories) == 1 else "Uncategorized",
                "memo" : self.memo
            }
        }

        response = requests.post(helper.YNAB_BASE_URL + "budgets/" + helper.getEnvs("budgetId") + "/transactions", data=json.dumps(body), headers=helper.setHeaders("ynab"))

        try:
            response.raise_for_status()
            print("Transaction created successfully")
        except requests.exceptions.HTTPError as http_err:
            print("An HTTP Error has occurred.\nStatus Code: " + str(http_err.response.status_code) + "\nError: " + http_err.response.reason)

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
        print("Setting up Account Databases...")
        self.setAccountDatabase()
        
        self.categories = []
        for cat in payload["categories"]:
            self.categories.append(YNABCategory(cat))
        print("Setting up Category Databases...")
        self.setCategoryDatabase()
        
        self.categoryGroups = []
        for catGroup in payload["category_groups"]:
            self.categoryGroups.append(YNABCategoryGroup(catGroup))
        print("Setting up Category Group Databases...")
        self.setCategoryGroupDatabase()
        
        self.payees = []
        for pay in payload["payees"]:
            self.payees.append(YNABPayee(pay))
        print("Setting up Payee Databases...")
        self.setPayeeDatabase()

        self.transactions = []
        for transaction in payload["transactions"]:
            self.transactions.append(YNABTransaction(jsonPayload=transaction))
        print("Setting up Payee->Category Databases...")
        self.setPayeeCategoryDatabase()

    def setAccountDatabase(self):
        helper.setDatabase("accounts", self.accounts, "id")
        helper.setDatabase("accounts", self.accounts, "name")

    def setPayeeDatabase(self):
        helper.setDatabase("payees", self.payees, "id")
        helper.setDatabase("payees", self.payees, "name")

    def setCategoryGroupDatabase(self):
        helper.setDatabase("category_groups", self.categoryGroups, "id")
        helper.setDatabase("category_groups", self.categoryGroups, "name")

    def setCategoryDatabase(self):
        helper.setDatabase("category", self.categories, "id")
        helper.setDatabase("category", self.categories, "name")

    def setPayeeCategoryDatabase(self):
        payeeToCategories = shelve.open("databases/payeeToCategories")
        categories = shelve.open("databases/categories__id")

        for transaction in self.transactions:
            if transaction.categoryId and "Transfer : " not in transaction.payeeName:
                if transaction.categoryId not in categories:
                    response = requests.get(helper.YNAB_BASE_URL + "budgets/" + helper.getEnvs("budgetId") + "/categories/" + transaction.categoryId, headers=helper.setHeaders("ynab")).json()["data"]["category"]
                    self.categories.append(YNABCategory(response))
                    categories[transaction.categoryId] = YNABCategory(response)

                if transaction.payeeName not in payeeToCategories:
                    payeeToCategories[transaction.payeeName] = set()
                    
                payeeToCategories[transaction.payeeName].add(categories[transaction.categoryId])

        categories.close()
        payeeToCategories.close()