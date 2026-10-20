from datetime import UTC, datetime
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
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC))
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC)
    )
    transaction_count: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return (
            f"<PayeeCategoryMapping(payee='{self.payee_name}', "
            f"category='{self.category_name}')>"
        )


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LedgerEntry(Base):
    """One row per Up transaction: the outcome of forwarding it to YNAB."""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    up_transaction_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20))  # forwarded, skipped, failed
    ynab_transaction_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<LedgerEntry(up_id='{self.up_transaction_id}', "
            f"status='{self.status}', attempts={self.attempts})>"
        )
