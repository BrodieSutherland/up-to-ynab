import os
import requests
from flask import Flask, request, jsonify
from database import init_db, get_ynab_account_id, store_account_mapping, get_payee_category_id, store_payee_mapping, store_category

app = Flask(__name__)

YNAB_API_TOKEN = None
YNAB_BUDGET_ID = None

@app.before_first_request
def setup():
    global YNAB_API_TOKEN, YNAB_BUDGET_ID
    YNAB_API_TOKEN = os.getenv('YNAB_API_TOKEN')
    YNAB_BUDGET_ID = os.getenv('YNAB_BUDGET_ID')
    if not YNAB_API_TOKEN or not YNAB_BUDGET_ID:
        raise RuntimeError("YNAB_API_TOKEN and YNAB_BUDGET_ID environment variables must be set")
    init_db()
    populate_initial_data()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    
    try:
        transaction = TransactionParser.from_json(data)
    except KeyError as e:
        return jsonify({"error": str(e)}), 400
    
    if transaction.data.attributes.status == "SETTLED":
        account_name = transaction.data.relationships.account.data.id
        payee_name = transaction.data.attributes.rawText

        ynab_account_id = get_ynab_account_id(account_name)
        if not ynab_account_id:
            ynab_account_id = find_and_store_ynab_account_id(account_name)

        ynab_category_id = get_payee_category_id(payee_name)
        if not ynab_category_id:
            ynab_category_id = find_and_store_payee_category_id(payee_name)

        ynab_transaction = TransactionConverter.to_ynab(transaction, payee_id, ynab_category_id)
        response = push_to_ynab(ynab_transaction)
        return jsonify(response), 200
    
    return jsonify({"status": "received"}), 200

def find_and_store_ynab_account_id(account_name):
    headers = {
        'Authorization': f'Bearer {YNAB_API_TOKEN}'
    }
    url = f'https://api.youneedabudget.com/v1/budgets/{YNAB_BUDGET_ID}/accounts'
    response = requests.get(url, headers=headers)
    accounts = response.json().get('data', {}).get('accounts', [])

    for account in accounts:
        if account['name'].lower() == account_name.lower():
            ynab_account_id = account['id']
            store_account_mapping(account_name, account['id'], ynab_account_id)
            return ynab_account_id
    return None

def find_and_store_payee_category_id(payee_name):
    headers = {
        'Authorization': f'Bearer {YNAB_API_TOKEN}'
    }
    url = f'https://api.youneedabudget.com/v1/budgets/{YNAB_BUDGET_ID}/payees'
    response = requests.get(url, headers=headers)
    payees = response.json().get('data', {}).get('payees', [])

    for payee in payees:
        if payee['name'].lower() == payee_name.lower():
            ynab_category_id = payee.get('category_id')
            store_payee_mapping(payee['id'], payee_name, ynab_category_id)
            return ynab_category_id
    return None

def push_to_ynab(ynab_transaction: YNAB):
    headers = {
        'Authorization': f'Bearer {YNAB_API_TOKEN}',
        'Content-Type': 'application/json'
    }
    url = f'https://api.youneedabudget.com/v1/budgets/{YNAB_BUDGET_ID}/transactions'
    response = requests.post(url, headers=headers, json=ynab_transaction)
    return response.json()

def populate_initial_data():
    headers = {
        'Authorization': f'Bearer {YNAB_API_TOKEN}'
    }

    # Fetch YNAB categories
    category_url = f'https://api.youneedabudget.com/v1/budgets/{YNAB_BUDGET_ID}/categories'
    response = requests.get(category_url, headers=headers)
    categories = response.json().get('data', {}).get('category_groups', [])
    for category_group in categories:
        for category in category_group['categories']:
            store_category(category['id'], category['name'])

    # Fetch YNAB transactions to determine payee categories
    transactions_url = f'https://api.youneedabudget.com/v1/budgets/{YNAB_BUDGET_ID}/transactions'
    response = requests.get(transactions_url, headers=headers)
    transactions = response.json().get('data', {}).get('transactions', [])
    
    payee_category_map = {}
    for transaction in transactions:
        payee_id = transaction.get('payee_id')
        category_id = transaction.get('category_id')
        if payee_id and category_id:
            if payee_id not in payee_category_map:
                payee_category_map[payee_id] = set()
            payee_category_map[payee_id].add(category_id)
    
    for payee_id, category_ids in payee_category_map.items():
        if len(category_ids) == 1:
            ynab_category_id = list(category_ids)[0]
            store_payee_mapping(payee_id, None, ynab_category_id)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
