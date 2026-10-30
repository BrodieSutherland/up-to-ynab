from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LedgerEntry(Base):
    """One row per Up transaction: the outcome of forwarding it to YNAB."""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    up_transaction_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20)
    )  # forwarded, skipped, failed, deleted
    ynab_transaction_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    attempts: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<LedgerEntry(up_id='{self.up_transaction_id}', "
            f"status='{self.status}', attempts={self.attempts})>"
        )


class WebhookSecret(Base):
    """The signing secret Up returned when this app created a webhook."""

    __tablename__ = "webhook_secrets"

    webhook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    secret_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    def __repr__(self) -> str:
        return f"<WebhookSecret(webhook_id='{self.webhook_id}')>"
