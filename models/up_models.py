from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class UpWebhookEventData(BaseModel):
    """Up webhook event data model."""

    id: str
    type: str
    attributes: Dict[str, Any]
    relationships: Optional[Dict[str, Any]] = None

    @property
    def event_type(self) -> str:
        """Get the event type from attributes."""
        return self.attributes.get("eventType", "")

    @property
    def created_at(self) -> Optional[str]:
        """Get the creation timestamp."""
        return self.attributes.get("createdAt")

    @property
    def transaction_id(self) -> Optional[str]:
        """Extract transaction ID from relationships."""
        if not self.relationships:
            return None

        transaction_data = self.relationships.get("transaction", {}).get("data")
        return transaction_data.get("id") if transaction_data else None


class UpWebhookEvent(BaseModel):
    """Up webhook event model."""

    data: UpWebhookEventData

    class Config:
        json_schema_extra = {
            "example": {
                "data": {
                    "type": "webhook-events",
                    "id": "01234567-89ab-cdef-0123-456789abcdef",
                    "attributes": {
                        "eventType": "TRANSACTION_CREATED",
                        "createdAt": "2024-01-15T10:30:00+00:00",
                    },
                    "relationships": {
                        "transaction": {
                            "data": {
                                "type": "transactions",
                                "id": "01234567-89ab-cdef-0123-456789abcdef",
                            }
                        }
                    },
                }
            }
        }


class UpMoney(BaseModel):
    """Up money amount model."""

    currency_code: str = Field(alias="currencyCode")
    value: str
    value_in_base_units: int = Field(alias="valueInBaseUnits")

    @property
    def decimal_value(self) -> Decimal:
        """Get the decimal value of the amount."""
        return Decimal(self.value)


class UpAccount(BaseModel):
    """Up account model."""

    id: str
    display_name: str = Field(alias="displayName")
    account_type: str = Field(alias="accountType")
    ownership_type: str = Field(alias="ownershipType")
    balance: UpMoney
    created_at: datetime = Field(alias="createdAt")


class UpCategory(BaseModel):
    """Up category model."""

    id: str
    name: str
    colour: Optional[str] = None


class UpTransactionAttributes(BaseModel):
    """Up transaction attributes model."""

    status: str
    raw_text: Optional[str] = Field(alias="rawText", default=None)
    description: str
    message: Optional[str] = None
    is_categorizable: bool = Field(alias="isCategorizable")
    hold_info: Optional[Dict[str, Any]] = Field(alias="holdInfo", default=None)
    round_up: Optional[Dict[str, Any]] = Field(alias="roundUp", default=None)
    cashback: Optional[Dict[str, Any]] = None
    amount: UpMoney
    foreign_amount: Optional[UpMoney] = Field(alias="foreignAmount", default=None)
    currency_conversion_fee: Optional[UpMoney] = Field(
        alias="currencyConversionFee", default=None
    )
    settled_at: Optional[datetime] = Field(alias="settledAt", default=None)
    created_at: datetime = Field(alias="createdAt")
    # Additional fields from the actual API response
    card_purchase_method: Optional[Dict[str, Any]] = Field(
        alias="cardPurchaseMethod", default=None
    )
    transaction_type: Optional[str] = Field(alias="transactionType", default=None)
    note: Optional[str] = None
    performing_customer: Optional[Dict[str, Any]] = Field(
        alias="performingCustomer", default=None
    )
    deep_link_url: Optional[str] = Field(alias="deepLinkURL", default=None)

    @field_validator("settled_at", "created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class UpTransactionRelationships(BaseModel):
    """Up transaction relationships model."""

    account: Dict[str, Any]
    category: Optional[Dict[str, Any]] = None
    parent_category: Optional[Dict[str, Any]] = Field(
        alias="parentCategory", default=None
    )
    tags: Optional[Dict[str, Any]] = None
    attachment: Optional[Dict[str, Any]] = None
    transfer_account: Optional[Dict[str, Any]] = Field(
        alias="transferAccount", default=None
    )


class UpTransaction(BaseModel):
    """Up transaction model."""

    id: str
    type: str
    attributes: UpTransactionAttributes
    relationships: UpTransactionRelationships

    @property
    def payee(self) -> str:
        """Get the transaction description as payee."""
        return self.attributes.description

    @property
    def amount_milliunits(self) -> int:
        """Get amount in milliunits for YNAB (multiply by 10)."""
        return self.attributes.amount.value_in_base_units * 10

    @property
    def is_internal_transfer(self) -> bool:
        """Check if this is an internal transfer."""
        from utils.config import get_settings

        settings = get_settings()

        return any(
            transfer_string in self.payee
            for transfer_string in settings.internal_transfer_strings
        )

    @property
    def date(self) -> str:
        """Get transaction date in YNAB format (YYYY-MM-DD)."""
        date_to_use = self.attributes.settled_at or self.attributes.created_at
        return date_to_use.strftime("%Y-%m-%d")


class UpTransactionResponse(BaseModel):
    """Up API transaction response model."""

    data: UpTransaction
