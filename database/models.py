from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class PayeeCategoryMapping(Base):
    """Model for storing payee to category mappings."""

    __tablename__ = "payee_category_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    payee_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    category_id: Mapped[str] = mapped_column(String(50))
    category_name: Mapped[str] = mapped_column(String(255))
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    transaction_count: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<PayeeCategoryMapping(payee='{self.payee_name}', category='{self.category_name}')>"


class ProcessedTransaction(Base):
    """Model for tracking processed transactions to avoid duplicates."""

    __tablename__ = "processed_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    up_transaction_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    ynab_transaction_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    payee_name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column()  # In milliunits
    transaction_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(
        String(20), default="processed"
    )  # processed, failed, skipped
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ProcessedTransaction(up_id='{self.up_transaction_id}', payee='{self.payee_name}', status='{self.status}')>"
