import os
import mysql.connector
from mysql.connector import errorcode

def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv('MYSQL_HOST'),
            user=os.getenv('MYSQL_USER'),
            password=os.getenv('MYSQL_PASSWORD'),
            database=os.getenv('MYSQL_DATABASE')
        )
        return conn
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("Something is wrong with your user name or password")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            print("Database does not exist")
        else:
            print(err)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            bank_account_name VARCHAR(255) PRIMARY KEY,
            bank_account_id VARCHAR(255),
            ynab_account_id VARCHAR(255)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payees (
            bank_payee_id VARCHAR(255) PRIMARY KEY,
            bank_payee_name VARCHAR(255),
            ynab_category_id VARCHAR(255)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            ynab_category_id VARCHAR(255) PRIMARY KEY,
            ynab_category_name VARCHAR(255)
        )
    ''')
    conn.commit()
    conn.close()

def get_ynab_account_id(bank_account_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT ynab_account_id FROM accounts WHERE bank_account_name = %s', (bank_account_name,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def store_account_mapping(bank_account_name, bank_account_id, ynab_account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO accounts (bank_account_name, bank_account_id, ynab_account_id)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            bank_account_id = VALUES(bank_account_id),
            ynab_account_id = VALUES(ynab_account_id)
    ''', (bank_account_name, bank_account_id, ynab_account_id))
    conn.commit()
    conn.close()

def get_payee_category_id(bank_payee_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT ynab_category_id FROM payees WHERE bank_payee_name = %s', (bank_payee_name,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def store_payee_mapping(bank_payee_id, bank_payee_name, ynab_category_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payees (bank_payee_id, bank_payee_name, ynab_category_id)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            bank_payee_name = VALUES(bank_payee_name),
            ynab_category_id = VALUES(ynab_category_id)
    ''', (bank_payee_id, bank_payee_name, ynab_category_id))
    conn.commit()
    conn.close()

def store_category(ynab_category_id, ynab_category_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO categories (ynab_category_id, ynab_category_name)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            ynab_category_name = VALUES(ynab_category_name)
    ''', (ynab_category_id, ynab_category_name))
    conn.commit()
    conn.close()
