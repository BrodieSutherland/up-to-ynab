from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Amount:
    currencyCode: str
    value: str
    valueInBaseUnits: int

@dataclass
class HoldInfo:
    amount: Amount
    foreignAmount: Optional[Amount] = None

@dataclass
class RoundUp:
    amount: Amount
    boostPortion: Optional[str] = None

@dataclass
class CardPurchaseMethod:
    method: str
    cardNumberSuffix: str

@dataclass
class PerformingCustomer:
    displayName: str

@dataclass
class AccountData:
    type: str
    id: str

@dataclass
class Links:
    related: str

@dataclass
class Account:
    data: AccountData
    links: Links

@dataclass
class Category:
    data: Optional[str]
    links: Links

@dataclass
class Tags:
    data: List[str]
    links: Links

@dataclass
class Relationships:
    account: Account
    transferAccount: Optional[str]
    category: Category
    parentCategory: Optional[str]
    tags: Tags
    attachment: Optional[str]

@dataclass
class LinksSelf:
    self: str

@dataclass
class Attributes:
    status: str
    rawText: str
    description: str
    message: Optional[str]
    isCategorizable: bool
    holdInfo: HoldInfo
    roundUp: RoundUp
    cashback: Optional[str]
    amount: Amount
    foreignAmount: Amount
    cardPurchaseMethod: CardPurchaseMethod
    settledAt: str
    createdAt: str
    transactionType: Optional[str]
    note: Optional[str]
    performingCustomer: PerformingCustomer

@dataclass
class Data:
    type: str
    id: str
    attributes: Attributes
    relationships: Relationships
    links: LinksSelf

@dataclass
class Transaction:
    data: Data
