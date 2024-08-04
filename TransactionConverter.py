import upClasses, ynabClasses

class TransactionConverter:
    @staticmethod
    def to_ynab(transaction: upClasses.Transaction) -> ynabClasses.YNAB:
        # Extract attributes and relationships from the Transaction object
        attributes = transaction.data.attributes
        relationships = transaction.data.relationships
        
        # Map the attributes and relationships to the YNAB Transaction class
        ynab_transaction = ynabClasses.Transaction(
            id=transaction.data.id,
            date=attributes.createdAt[:10],  # Extract the date part
            amount=int(float(attributes.amount.value) * 1000),  # Convert amount to an integer in milli-units
            memo=attributes.description,
            cleared="cleared" if attributes.status == "SETTLED" else "uncleared",
            approved=True,  # Assuming all transactions are approved
            flag_color="red",  # Default flag color
            flag_name=None,  # Assuming no flag name is provided
            account_id=relationships.account.data.id,
            payee_id=None,  # Not available in the original data
            category_id=None,  # Not available in the original data
            transfer_account_id=None,  # Not available in the original data
            transfer_transaction_id=None,  # Not available in the original data
            matched_transaction_id=None,  # Not available in the original data
            import_id=None,  # Not available in the original data
            import_payee_name=attributes.rawText,
            import_payee_name_original=attributes.rawText,
            debt_transaction_type=None,  # Not available in the original data
            deleted=False,  # Assuming not deleted
            account_name=None,  # Not available in the original data
            payee_name=attributes.rawText,
            category_name=None,  # Not available in the original data
            subtransactions=[]  # Assuming no subtransactions
        )
        
        return ynabClasses.YNAB(data=ynabClasses.Data(transaction=ynab_transaction))

# # Example usage:
# ynab_transaction_instance = TransactionConverter.to_ynab(transaction_instance)
# print(ynab_transaction_instance)
