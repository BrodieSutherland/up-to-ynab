from os import getenv
import requests
import helper
import shelve
import json

INTERNAL_TRANSFER_STRINGS = ["Transfer to ", "Cover to ", "Quick save transfer to "]
INCORRECT_TRANSFER_STRINGS = [
    "Transfer from ",
    "Cover from ",
    "Quick save transfer from ",
]

# UP API CLASSES
class UpWebhookEvent:
    def __init__(self, payload: dict):
        self.id = payload["id"]
        self.type = payload["attributes"]["eventType"]
        self.date = payload["attributes"]["createdAt"]
        try:
            self.transactionId = payload["relationships"]["transaction"]["data"]["id"]
        except:
            print("Not a transaction?")

    def getTransaction(self):
        """Retrieves the Up transaction from the API and stores it as an UpTransaction under self.transaction"""
        response = requests.get(
            helper.UP_BASE_URL + "transactions/" + self.transactionId,
            headers=helper.setHeaders("up"),
        )

        try:
            response.raise_for_status()
            self.transaction = UpTransaction(response.json()["data"])
        except requests.exceptions.HTTPError as http_err:
            print(
                "An HTTP Error has occurred.\nStatus Code: "
                + str(http_err.response.status_code)
                + "\nError: "
                + http_err.response.reason
            )

    def convertTransaction(self):
        """Converts the Up transaction to a YNAB Transaction"""
        if self.transaction:
            self.ynabTransaction = YNABTransaction(upTransaction=self.transaction)
        else:
            print("There is currently no transaction against this Event")


class UpTransaction:
    def __init__(self, payload: dict):
        self.id = payload["id"]
        attributes = payload["attributes"]
        self.isInternal = (
            True
            if any(
                internalString in attributes["description"]
                for internalString in INTERNAL_TRANSFER_STRINGS
            )
            else False
        )
        self.status = attributes["status"]
        self.payee = attributes["description"]
        self.message = attributes["message"]
        self.value = float(attributes["amount"]["value"])
        self.date = attributes["createdAt"]
        self.accountId = payload["relationships"]["account"]["data"]["id"]

        self.accountName = helper.getVariableFromShelf(
            "databases/up_accounts", self.accountId
        ).name

        if getenv("DEBUG_MODE"):
            print("--------------------------------------------------------")
            print(self)

    def __str__(self) -> str:
        return (
            "UP TRANSACTION:\n"
            + "Date: "
            + self.date
            + "\n"
            + "Value: "
            + str(self.value)
            + "\n"
            + "Payee: "
            + self.payee
            + "\n"
            + "Account: "
            + self.accountName
            + "\n"
            + "Message: "
            + self.message
            + "\n"
            + "Status: "
            + self.status
            + "\n"
            + "Is Internal: "
            + str(self.isInternal)
        )


class UpAccount:
    def __init__(self, payload: dict):
        self.id = payload["id"]
        self.name = payload["attributes"]["displayName"]
        self.type = payload["attributes"]["accountType"]

        if getenv("DEBUG_MODE"):
            print(self)

    def __str__(self) -> str:
        return "UP ACCOUNT:\nName: " + self.name + "\nType: " + self.type


# YNAB API CLASSES
class YNABBase:
    def __init__(self, payload: dict):
        self.id = payload["id"]
        self.name = payload["name"]


class YNABTransaction(YNABBase):
    def __init__(self, jsonPayload: dict = None, upTransaction: UpTransaction = None):
        if jsonPayload != None:
            self.id = jsonPayload["id"]
            self.accountId = jsonPayload["account_id"]
            self.date = jsonPayload["date"][0:10]
            self.amount = int(float(jsonPayload["amount"])) * 1000
            self.categoryId = jsonPayload["category_id"]
            self.multi = False if jsonPayload["subtransactions"] == [] else True
            self.memo = jsonPayload["memo"]
            self.categories = []

            self.payeeId = jsonPayload["payee_id"]
            if "payee_name" in jsonPayload:
                self.payeeName = jsonPayload["payee_name"]
            else:
                self.payeeName = helper.getVariableFromShelf(
                    "databases/payees__id", self.payeeId
                ).name

        elif upTransaction != None:
            self.accountId = helper.getVariableFromShelf(
                "databases/accounts__name", upTransaction.accountName
            ).id

            self.date = upTransaction.date[0:10]
            self.amount = int(upTransaction.value * 1000)
            self.memo = upTransaction.message

            if upTransaction.payee == "Round Up":
                self.payeeName = None
                self.payeeId = helper.TRANSACTIONAL_ACCOUNT_ID
                self.categories = []
            elif upTransaction.isInternal:
                # Some wack shit in here because the transferId value in the Up Transaction payload doesn't work/is very rarely shown
                # so I've had to build some janky shit to get around it, keen to turf this ASAP

                accountName = upTransaction.payee
                for sub in INTERNAL_TRANSFER_STRINGS:
                    accountName = accountName.replace(sub, "")
                for account in helper.UP_ACCOUNTS:
                    if accountName in account:
                        self.payeeId = helper.getVariableFromShelf(
                            "databases/accounts__name", account
                        ).transferId
                self.categories = []
                self.payeeName = None
            else:
                self.payeeName = upTransaction.payee
                payee = helper.getVariableFromShelf(
                    "databases/payees__name", self.payeeName
                )
                self.payeeId = payee.id if payee != None else None
                categories = helper.getVariableFromShelf(
                    "databases/payeeToCategories", self.payeeName
                )
                self.categories = (
                    list(
                        helper.getVariableFromShelf(
                            "databases/payeeToCategories", self.payeeName
                        )
                    )
                    if categories != None
                    else []
                )

        if getenv("DEBUG_MODE"):
            print(self)

    def sendNewYNABTransaction(self):
        """Sends the YNAB Transaction to YNAB"""
        try:
            category = (
                self.categories[0].name
                if len(self.categories) == 1
                else "Uncategorized"
            )

            body = {
                "transaction": {
                    "account_id": self.accountId,
                    "date": self.date,
                    "amount": self.amount,
                    "payee_name": self.payeeName if self.payeeName else "",
                    "payee_id": self.payeeId,
                    "category_name": category,
                    "memo": self.memo,
                }
            }

            if getenv("DEBUG_MODE"):
                print(body)

            response = requests.post(
                helper.YNAB_BASE_URL
                + "budgets/"
                + helper.getEnvs("budgetId")
                + "/transactions",
                data=json.dumps(body),
                headers=helper.setHeaders("ynab"),
            )
        except:
            print(
                "Looks like something has gone wrong in the YNAB Transaction payload generator, here's some info:"
            )
            if self.accountId:
                print("Account ID: " + self.accountId)
            if self.date:
                print("Date: " + self.date)
            if self.amount:
                print("Amount: " + str(self.amount))
            if self.payeeName:
                print("Payee Name: " + self.payeeName)
            if self.payeeId:
                print("Payee ID: " + self.payeeId)
            if category:
                print("Category: " + category)
            if self.memo:
                print("Memo: " + self.memo)

        try:
            response.raise_for_status()
            print("Transaction created successfully")
        except requests.exceptions.HTTPError as http_err:
            print(
                "An HTTP Error has occurred.\nStatus Code: "
                + str(http_err.response.status_code)
                + "\nError: "
                + http_err.response.reason
            )
        print("--------------------------------------------------------")

    def __str__(self) -> str:
        return (
            "YNAB TRANSACTION:\n"
            + "Date: "
            + self.date
            + "\n"
            + "Amount: "
            + str(self.amount)
            + "\n"
            + "Payee: "
            + (self.payeeName if self.payeeName else "Internal Transfer")
        )


class YNABAccount(YNABBase):
    def __init__(self, payload: dict):
        YNABBase.__init__(self, payload)
        self.transferId = payload["transfer_payee_id"]


class YNABPayee(YNABBase):
    def __init__(self, payload: dict):
        YNABBase.__init__(self, payload)


class YNABCategory(YNABBase):
    def __init__(self, payload: dict):
        YNABBase.__init__(self, payload)


class YNABBudget(YNABBase):
    def __init__(self, payload: dict):
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

        self.payees = []
        for pay in payload["payees"]:
            self.payees.append(YNABPayee(pay))
        print("Setting up Payee Databases...")
        self.setPayeeDatabase()

        self.transactions = []
        response = requests.get(
            helper.YNAB_BASE_URL
            + "budgets/"
            + helper.getEnvs("budgetId")
            + "/transactions",
            headers=helper.setHeaders("ynab"),
        )

        if response.status_code == 200:
            for transaction in response.json()["data"]["transactions"]:
                self.transactions.append(YNABTransaction(jsonPayload=transaction))
            print("Setting up Payee->Category Databases...")
            self.setPayeeCategoryDatabase()

    def setAccountDatabase(self):
        """Sets the account database"""
        helper.setDatabase("accounts", self.accounts, "id")
        helper.setDatabase("accounts", self.accounts, "name")

    def setPayeeDatabase(self):
        """Sets the payee database"""
        helper.setDatabase("payees", self.payees, "id")
        helper.setDatabase("payees", self.payees, "name")

    def setCategoryDatabase(self):
        """Sets the category database"""
        helper.setDatabase("category", self.categories, "id")
        helper.setDatabase("category", self.categories, "name")

    def setPayeeCategoryDatabase(self):
        """Sets the payee->category database"""
        payeeToCategories = shelve.open("databases/payeeToCategories")
        categories = shelve.open("databases/categories__id")

        for transaction in self.transactions:
            if (
                transaction.categoryId
                and "Transfer : " not in transaction.payeeName
                and not transaction.multi
            ):
                if transaction.categoryId not in categories:
                    response = requests.get(
                        helper.YNAB_BASE_URL
                        + "budgets/"
                        + helper.getEnvs("budgetId")
                        + "/categories/"
                        + transaction.categoryId,
                        headers=helper.setHeaders("ynab"),
                    ).json()["data"]["category"]
                    self.categories.append(YNABCategory(response))
                    categories[transaction.categoryId] = YNABCategory(response)

                if transaction.payeeName not in payeeToCategories:
                    payeeToCategories[transaction.payeeName] = set()

                payeeToCategories[transaction.payeeName].add(
                    categories[transaction.categoryId]
                )

        categories.close()
        payeeToCategories.close()
