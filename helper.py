import json
import os
from pathlib import Path
import shelve
import requests
import classes

YNAB_BASE_URL = "https://api.youneedabudget.com/v1/"
UP_BASE_URL = "https://api.up.com.au/api/v1/"

def handleWebhookEvent(event):
    if(event.type == "TRANSACTION_CREATED"):
        event.getTransaction()
        event.convertTransaction()
        event.ynabTransaction.sendNewYNABTransaction()

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

        for i in payload:
            account = classes.UpAccount(i)

            # Used to get the transfer ID of the Transactional Account to handle Round Up transfers
            if account.type == "TRANSACTIONAL":
                ynabAccounts = shelve.open("databases/accounts__name")
                global TRANSACTIONAL_ACCOUNT_ID
                TRANSACTIONAL_ACCOUNT_ID = ynabAccounts[account.name].transferId
                ynabAccounts.close()

            UP_ACCOUNTS.append(account.name)

            upAccounts[account.id] = account

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

    global UP_ACCOUNTS
    UP_ACCOUNTS = []

    response = requests.get(YNAB_BASE_URL + "budgets/" + getEnvs("budgetId"), headers = setHeaders("ynab"))

    if response.status_code == 200:
        budget = classes.YNABBudget(response.json()["data"]["budget"])

        print("Setting up Up Account Databases...")
        setUpAccountDatabases()
    else:
        raise RuntimeError("Couldn't access the YNAB API. Code: " + str(response.status_code) + "\nError: " + response.reason)

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

def pingWebhook():
    body = {
        "data" : {
            "attributes" : {
                "url" : getEnvs("HEROKU_BASE_URL") + "up_webhook",
                "description" : "An automatic webhook to transfer data from Up into YNAB"
            }
        }
    }

    response = requests.get(UP_BASE_URL + "webhooks/", headers=setHeaders("up"))

    try:
        response.raise_for_status()
        if len(response.json()["data"]) > 0:
            for hook in response.json()["data"]:
                if hook["attributes"]["url"] == getEnvs("HEROKU_BASE_URL") + "up_webhook":
                    return True
            return False
        else:
            return False
    except requests.exceptions.HTTPError as http_err:
        print("An HTTP Error has occurred.\nStatus Code: " + str(http_err.response.status_code) + "\nError: " + http_err.response.reason)

def setVariableFromShelf(shelf, key):
    database = shelve.open(shelf)
    variable = None

    if key in database:
        variable = database[key]

    database.close()

    return variable