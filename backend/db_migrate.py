from typing import Iterable
from flask import current_app
from sqlalchemy import text


def _table_has_column(conn, table: str, column: str) -> bool:
    dialect = conn.engine.dialect.name
    if dialect == 'sqlite':
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == column for r in rows)
    else:
        # Generic information_schema for others
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name=:t"
        ), {"t": table}).fetchall()
        return any(r[0] == column for r in rows)


def ensure_user_columns(db):
    """Add missing columns to users table for email verification."""
    with db.engine.begin() as conn:
        # email_verified
        if not _table_has_column(conn, 'users', 'email_verified'):
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT 0 NOT NULL"))
            except Exception as e:
                current_app.logger.warning("Add column email_verified failed: %s", e)
        # verified_at
        if not _table_has_column(conn, 'users', 'verified_at'):
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN verified_at DATETIME NULL"))
            except Exception as e:
                current_app.logger.warning("Add column verified_at failed: %s", e)


def ensure_image_columns(db):
    """Add missing columns to image_results for billing and analytics."""
    with db.engine.begin() as conn:
        if not _table_has_column(conn, 'image_results', 'cost_credits'):
            try:
                conn.execute(text("ALTER TABLE image_results ADD COLUMN cost_credits REAL DEFAULT 0 NOT NULL"))
            except Exception as e:
                current_app.logger.warning("Add column cost_credits failed: %s", e)
        if not _table_has_column(conn, 'image_results', 'request_ip'):
            try:
                conn.execute(text("ALTER TABLE image_results ADD COLUMN request_ip VARCHAR(64) NULL"))
            except Exception as e:
                current_app.logger.warning("Add column request_ip failed: %s", e)
