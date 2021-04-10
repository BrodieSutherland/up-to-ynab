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

def setDatabase(shelf, payload):
    idDatabase = shelve.open("databases/" + shelf + "__id")
    nameDatabase = shelve.open("databases/" + shelf + "__name")

    for i in payload:
        idDatabase[i["id"]] = i["name"]
        nameDatabase[i["name"]] = i["id"]
    
    idDatabase.close()
    nameDatabase.close()

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
        payload = response.json()["data"]["budget"]

        for base in YNAB_DATABASES:
            setDatabase(base, payload[base])
    else:
        raise RuntimeError("Couldn't access the YNAB API. Code: " + str(response.status_code) + "\nError: " + response.reason)

    payeeToCat = shelve.open("databases/payeeToCategories")
    cats = shelve.open("databases/categories__id")
    payees = shelve.open("databases/payees__id")

    for i in response.json()["data"]["budget"]["transactions"]:
        try:
            if i["category_id"]:
                try:
                    payeeToCat[payees[i["payee_id"]]] = payeeToCat[payees[i["payee_id"]]].add(cats[i["category_id"]])
                except Exception:
                    payeeToCat[payees[i["payee_id"]]] = set([cats[i["category_id"]]])
        except Exception:
            print("Split Transaction?")

    payeeToCat.close()
    cats.close()
    payees.close()

    response = requests.get(UP_BASE_URL + "accounts/", headers = setHeaders("up"))

    if response.status_code == 200:
        payload = response.json()["data"]

        upAccounts = shelve.open("databases/up_accounts")

        for i in payload:
            upAccounts[i["id"]] = i["attributes"]["displayName"]

        upAccounts.close()
    else:
        raise RuntimeError("Couldn't access the YNAB API. Code: " + str(response.status_code) + "\nError: " + response.reason)

def createYNABTransaction(upTransaction):
    newYNABTransaction = classes.YNABTransaction(payload=upTransaction)
    payeeNameShelf = shelve.open("databases/payees__name")
    newYNABTransaction.payeeId = payeeNameShelf[newYNABTransaction.payeeName]
    payeeNameShelf.close()


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
    payeeToCat = shelve.open("databases/payeeToCategories")

    categories = []

    try:
        categories = list(payeeToCat[transactionObject.payeeName])
    except Exception:
        pass

    payeeToCat.close()

    body = {
        "transaction" : {
            "account_id" : transactionObject.accountId,
            "date" : transactionObject.date[0 : 10],
            "amount" : int(float(transactionObject.amount) * 1000),
            "payee_name" : transactionObject.payeeName,
            "category_name" : categories[0] if len(categories) == 1 else "Uncategorized",
            "memo" : transactionObject.memo if transactionObject.memo != None else ""
        }
    }

    response = requests.post(YNAB_BASE_URL + "budgets/" + getEnvs("budgetId") + "/transactions", data=json.dumps(body), headers=setHeaders("ynab"))

    try:
        response.raise_for_status()
        print("Transaction created successfully")
    except requests.exceptions.HTTPError as http_err:
        print("An HTTP Error has occurred.\nStatus Code: " + str(http_err.response.status_code) + "\nError: " + http_err.response.reason)