import json
import os
from pathlib import Path
import shelve
import requests
import classes
from threading import Lock

YNAB_BASE_URL = "https://api.youneedabudget.com/v1/"
UP_BASE_URL = "https://api.up.com.au/api/v1/"
LOCK = Lock()


def handleWebhookEvent(event):
    """Initiates the logic to transfer data from Up into YNAB"""
    if event.type == "TRANSACTION_CREATED":
        event.getTransaction()
        if not any(
            substring in event.transaction.payee
            for substring in classes.INCORRECT_TRANSFER_STRINGS
        ):
            event.convertTransaction()
            event.ynabTransaction.sendNewYNABTransaction()

        return (
            str(event.transaction.value)
            + " paid to "
            + str(event.transaction.payee)
            + " at "
            + str(event.transaction.date)
        )


def getEnvs(var: str) -> str:
    """Gets the environment variables from the Heroku environment"""
    if os.environ.get(var):
        return os.environ.get(var)
    else:
        print("Couldn't find this variable")


def setDatabase(shelf: str, objectList: list[str], key: str):
    """Sets a database with a list of objects for a given key value"""
    shelfDatabase = shelve.open("databases/" + shelf + "__" + key)

    for i in objectList:
        try:
            shelfDatabase[getattr(i, key)] = i
        except Exception:
            print("Couldn't set " + key + " for " + i.name)

    shelfDatabase.close()


def setUpAccountDatabases():
    """Sets the databases for all accounts in Up"""
    response = requests.get(UP_BASE_URL + "accounts/", headers=setHeaders("up"))

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
        raise RuntimeError(
            "Couldn't access the Up API. Code: "
            + str(response.status_code)
            + "\nError: "
            + response.reason
        )


def setHeaders(type: str) -> dict:
    """Sets the headers for the requests"""
    switch = {"up": "upKey", "ynab": "ynabKey"}

    headers = {
        "Authorization": "Bearer " + getEnvs(switch[type]),
        "Content-Type": "application/json",
    }
    return headers


def setAllYNABDatabases():
    """Sets the databases for all accounts in YNAB"""
    if not os.path.exists("databases"):
        os.makedirs("databases")

    global UP_ACCOUNTS
    UP_ACCOUNTS = []

    response = requests.get(
        YNAB_BASE_URL + "budgets/" + getEnvs("budgetId"), headers=setHeaders("ynab")
    )

    if response.status_code == 200:
        budget = classes.YNABBudget(response.json()["data"]["budget"])

        print("Setting up Up Account Databases...")
        setUpAccountDatabases()
    else:
        raise RuntimeError(
            "Couldn't access the YNAB API. Code: "
            + str(response.status_code)
            + "\nError: "
            + response.reason
        )


def createUpWebhook():
    """Creates a new Up Webhook"""
    body = {
        "data": {
            "attributes": {
                "url": getEnvs("BASE_URL"),
                "description": "An automatic webhook to transfer data from Up into YNAB",
            }
        }
    }

    response = requests.post(
        UP_BASE_URL + "webhooks/", data=json.dumps(body), headers=setHeaders("up")
    )

    try:
        response.raise_for_status()
        print("Webhook created Successfully")
    except requests.exceptions.HTTPError as http_err:
        print(
            "An HTTP Error has occurred.\nStatus Code: "
            + str(http_err.response.status_code)
            + "\nError: "
            + http_err.response.reason
        )


def pingWebhook() -> bool:
    """Checks if the webhook is active"""
    body = {
        "data": {
            "attributes": {
                "url": getEnvs("BASE_URL"),
                "description": "An automatic webhook to transfer data from Up into YNAB",
            }
        }
    }

    response = requests.get(UP_BASE_URL + "webhooks/", headers=setHeaders("up"))

    try:
        response.raise_for_status()
        if len(response.json()["data"]) > 0:
            for hook in response.json()["data"]:
                if hook["attributes"]["url"] == getEnvs("BASE_URL"):
                    return True
            return False
        else:
            return False
    except requests.exceptions.HTTPError as http_err:
        print(
            "An HTTP Error has occurred.\nStatus Code: "
            + str(http_err.response.status_code)
            + "\nError: "
            + http_err.response.reason
        )


def getVariableFromShelf(shelf: str, key: str) -> str:
    """Gets a variable from a shelf"""
    LOCK.acquire()

    database = shelve.open(shelf)
    variable = None

    if key in database:
        variable = database[key]

    database.close()

    LOCK.release()

    return variable


def setVariableToShelf(shelf: str, key: str, variable: str):
    """Sets a variable to a shelf"""
    LOCK.acquire()

    database = shelve.open(shelf)
    database[key] = variable

    database.close()

    LOCK.release()


def deleteVariableFromShelf(shelf: str, key: str):
    """Deletes a variable from a shelf"""
    LOCK.acquire()

    database = shelve.open(shelf)
    del database[key]
    database.close()

    LOCK.release()


def refresh():
    """Refreshes the databases"""
    print("Refreshing...")
    setAllYNABDatabases()
    print("Refresh Complete")
