import json
import os
from pathlib import Path
import shelve
import requests
import classes

YNAB_DATABASES = ["accounts", "payees", "category_groups", "categories"]
YNAB_BASE_URL = "https://api.youneedabudget.com/v1/"
UP_BASE_URL = "https://api.up.com.au/api/v1/"

def handleWebhookEvent(event):
    if(event.type == "TRANSACTION_CREATED"):
        event.getTransaction()
        event.convertTransaction()
        sendNewYNABTransaction(event.ynabTransaction)

        return str(event.transaction.value) + " paid to " + str(event.transaction.payee) + " at " + str(event.transaction.date)

def getEnvs(var):
    if os.environ.get(var):
        return os.environ.get(var)
    else:
        print("Couldn't find this variable")

def setDatabase(shelf, objectList, key):
    shelfDatabase = shelve.open("databases/" + shelf + "__" + key)

    for i in objectList:
        try:
            shelfDatabase[getattr(i, key)] = i
        except Exception:
            pass
    
    shelfDatabase.close()

def setUpAccountDatabases():
    response = requests.get(UP_BASE_URL + "accounts/", headers = setHeaders("up"))

    if response.status_code == 200:
        payload = response.json()["data"]

        upAccounts = shelve.open("databases/up_accounts")
        ynabAccounts = shelve.open("databases/accounts__name")

        for i in payload:
            account = classes.UpAccount(i)
            if account.type == "TRANSACTIONAL":
                global TRANSACTIONAL_ACCOUNT_ID
                TRANSACTIONAL_ACCOUNT_ID = ynabAccounts[account.name].transferId
            upAccounts[account.id] = account.name

        ynabAccounts.close()
        upAccounts.close()
    else:
        raise RuntimeError("Couldn't access the Up API. Code: " + str(response.status_code) + "\nError: " + response.reason)

def setHeaders(type):
    switch = {
        "up" : "upKey",
        "ynab" : "ynabKey"
    }

    headers = {
        "Authorization" : "Bearer " + getEnvs(switch[type]),
        "Content-Type" : "application/json"
    }
    return headers

def setAllYNABDatabases():
    if not os.path.exists('databases'):
        os.makedirs('databases')

    response = requests.get(YNAB_BASE_URL + "budgets/" + getEnvs("budgetId"), headers = setHeaders("ynab"))

    if response.status_code == 200:
        budget = classes.YNABBudget(response.json()["data"]["budget"])
    else:
        raise RuntimeError("Couldn't access the YNAB API. Code: " + str(response.status_code) + "\nError: " + response.reason)

    budget.setAccountDatabase()
    budget.setCategoryDatabase()
    budget.setCategoryGroupDatabase()
    budget.setPayeeDatabase()
    setUpAccountDatabases()

def createYNABTransaction(upTransaction):
    newYNABTransaction = classes.YNABTransaction(jsonPayload=upTransaction)
    return newYNABTransaction

def createUpWebhook():
    body = {
        "data" : {
            "attributes" : {
                "url" : getEnvs("HEROKU_BASE_URL") + "up_webhook",
                "description" : "An automatic webhook to transfer data from Up into YNAB"
            }
        }
    }
    response = requests.post(UP_BASE_URL + "webhooks/", data=json.dumps(body), headers=setHeaders("up"))

    try:
        response.raise_for_status()
        print("Webhook created Successfully")
    except requests.exceptions.HTTPError as http_err:
        print("An HTTP Error has occurred.\nStatus Code: " + str(http_err.response.status_code) + "\nError: " + http_err.response.reason)

def sendNewYNABTransaction(transactionObject):
    body = {
        "transaction" : {
            "account_id" : transactionObject.accountId,
            "date" : transactionObject.date,
            "amount" : transactionObject.amount,
            "payee_name" : transactionObject.payeeName if transactionObject.payeeName != None else "",
            "payee_id" : TRANSACTIONAL_ACCOUNT_ID if transactionObject.payeeName == None else "",
            "category_name" : transactionObject.categories[0] if len(transactionObject.categories) == 1 else "Uncategorized",
            "memo" : transactionObject.memo if transactionObject.memo != None else ""
        }
    }

    response = requests.post(YNAB_BASE_URL + "budgets/" + getEnvs("budgetId") + "/transactions", data=json.dumps(body), headers=setHeaders("ynab"))

    try:
        response.raise_for_status()
        print("Transaction created successfully")
    except requests.exceptions.HTTPError as http_err:
        print("An HTTP Error has occurred.\nStatus Code: " + str(http_err.response.status_code) + "\nError: " + http_err.response.reason)