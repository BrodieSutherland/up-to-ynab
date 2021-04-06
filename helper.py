import json
import os
from pathlib import Path
import shelve
import requests

DATABASES = ["accounts", "payees", "category_groups", "categories"]
YNAB_BASE_URL = "https://api.youneedabudget.com/v1/"
UP_BASE_URL = "https://api.up.com.au/api/v1/"

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
    database = shelve.open("databases/" + shelf)

    for i in payload:
        database[i["id"]] = i["name"]
    
    database.close()

def setHeaders(type):
    headers = {
        "Authorization" : "Bearer " + getEnvs()[type]
    }
    return headers

def setAllDatabases():
    response = requests.get(YNAB_BASE_URL + "budgets/" + getEnvs()["budget"], headers = setHeaders("ynab"))

    if response.status_code == 200:
        payload = response.json()["data"]["budget"]

        for base in DATABASES:
            setDatabase(base, payload[base])
    else:
        raise RuntimeError("Couldn't access the YNAB API. Code: " + str(response.status_code) + "\nError: " + response.reason)

