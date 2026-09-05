from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from backend.database.database import get_connection


logger = logging.getLogger(__name__)
KEY_PREFIX = "rail_live_"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_table() -> None:
    connection = get_connection()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                name TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                key_prefix TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_account ON api_keys(account_id, created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)")
        connection.commit()
    finally:
        connection.close()


def _masked(prefix: str) -> str:
    return f"{prefix}{'•' * 16}"


def create_api_key(account_id: str, name: str) -> dict[str, Any]:
    _ensure_table()
    clean_name = " ".join(name.split())
    if not clean_name or len(clean_name) > 80:
        raise ValueError("Key name must contain 1 to 80 characters.")
    raw_key = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key_id = secrets.token_hex(16)
    created_at = _now()
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO api_keys (id, account_id, name, key_hash, key_prefix, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
            """,
            (key_id, account_id, clean_name, _hash_key(raw_key), KEY_PREFIX, created_at),
        )
        connection.commit()
    finally:
        connection.close()
    return {
        "id": key_id,
        "name": clean_name,
        "key": raw_key,
        "prefix": KEY_PREFIX,
        "created_at": created_at,
        "last_used_at": None,
        "status": "active",
    }


def list_api_keys(account_id: str) -> list[dict[str, Any]]:
    _ensure_table()
    connection = get_connection()
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, name, key_prefix, created_at, last_used_at, revoked_at, status
            FROM api_keys WHERE account_id = ? ORDER BY created_at DESC
            """,
            (account_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "prefix": row["key_prefix"],
                "masked_key": _masked(row["key_prefix"]),
                "created_at": row["created_at"],
                "last_used_at": row["last_used_at"],
                "status": row["status"],
            }
            for row in rows
        ]
    finally:
        connection.close()


def revoke_api_key(account_id: str, key_id: str) -> bool:
    _ensure_table()
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE api_keys
            SET status = 'revoked', revoked_at = COALESCE(revoked_at, ?)
            WHERE id = ? AND account_id = ? AND status = 'active'
            """,
            (_now(), key_id, account_id),
        )
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def authenticate_api_key(presented_key: str) -> bool:
    """Validate a stored key and update only its last-used metadata."""

    if not presented_key:
        return False
    _ensure_table()
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT id FROM api_keys WHERE key_hash = ? AND status = 'active'",
            (_hash_key(presented_key),),
        ).fetchone()
        if row is None:
            return False
        connection.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (_now(), row[0]))
        connection.commit()
        return True
    finally:
        connection.close()


def account_id_from_environment(headers: dict[str, str]) -> str | None:
    supplied = (headers.get("X-Account-ID") or "").strip()
    if supplied:
        return supplied[:128]
    if os.getenv("RAILETA_REQUIRE_ACCOUNT_AUTH", "false").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    return os.getenv("RAILETA_DEVELOPMENT_ACCOUNT_ID", "local-development-account").strip() or "local-development-account"
