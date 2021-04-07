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
    if(event.type == "TRANSACTION_SETTLED"):
        event.getTransaction
        print(event.transaction.value + " paid to " + event.transaction.payee + " at " + event.transaction.settleDate)

def getEnvs():
    try:
        envVars = {
            # "up" : os.environ.get("upKey"),
            # "ynab" : os.environ.get("ynabKey"),
            # "budget" : os.environ.get("budgetId")
        }

        envVars["up"] = "up:yeah:2xxgep1iQ68y5cPEO83CUELIzYBdutebGLHnI5iPJSKdcOYlnTuyHQYY0wLxA4fpe9EBH3wbWZkWWlD6z52qpDORCGSfySbQNZogx7n7FstOZH4Ggh4EsF6efolb4fb2"
        envVars["ynab"] = "a7ff8750605bd1a5169078221cc0ff705628c639ed29a9cb9902501aba428114"
        envVars["budget"] = "0c8b0481-c89d-4ff9-8213-622798992665"
    except:
        print("cant find heroku vars, you better check this shit")

    return envVars

def setDatabase(shelf, payload):
    idDatabase = shelve.open("databases/" + shelf + "__id")
    nameDatabase = shelve.open("databases/" + shelf + "__name")

    for i in payload:
        idDatabase[i["id"]] = i["name"]
        idDatabase[i["name"]] = i["id"]
    
    idDatabase.close()
    nameDatabase.close()

def setHeaders(type):
    headers = {
        "Authorization" : "Bearer " + getEnvs()[type]
    }
    return headers

def setAllYNABDatabases():
    response = requests.get(YNAB_BASE_URL + "budgets/" + getEnvs()["budget"], headers = setHeaders("ynab"))

    if response.status_code == 200:
        payload = response.json()["data"]["budget"]

        for base in YNAB_DATABASES:
            setDatabase(base, payload[base])
    else:
        raise RuntimeError("Couldn't access the YNAB API. Code: " + str(response.status_code) + "\nError: " + response.reason)

def createYNABTransaction(upTransaction):
    newYNABTransaction = classes.YNABTransaction(transaction=upTransaction)
    payeeNameShelf = shelve.open("databases/payees__name")
    newYNABTransaction.payeeId = payeeNameShelf[newYNABTransaction.payeeName]
    payeeNameShelf.close()


    return newYNABTransaction

def getPayeeId(payeeName):
    pass

def createUpWebhook():
    body = {
        "data" : {
            "attributes" : {
                "url" : getEnvs()["HEROKU_BASE_URL"] + "/up_webhook",
                "description" : "An automatically created webhook to transfer data from Up into YNAB"
            }
        }
    }
    response = requests.post(UP_BASE_URL + "/webhooks", data=body, headers=setHeaders("up"))


    try:
        response.raise_for_status()
        print("Webhook created Successfully")
    except requests.exceptions.HTTPError as http_err:
        print("An HTTP Error has occurred: " + http_err)
