"""Alembic environment: runs on the connection the app hands in."""

from alembic import context

from database.models import Base

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=True,
)
with context.begin_transaction():
    context.run_migrations()
