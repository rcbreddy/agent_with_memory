"""Authentication service: PBKDF2 password hashing, opaque bearer sessions (stored hashed, with
expiry) and the `current_user` dependency.

Every user gets a stable user_id and their own isolated Hindsight memory bank.
"""

import hashlib
import hmac
import logging
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.db import connect, now_iso

log = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)

PBKDF2_ITERATIONS = 200_000


@dataclass(frozen=True)
class User:
    id: str
    username: str
    bank_id: str  # this user's private Hindsight memory bank


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except ValueError:
        return False
    return hmac.compare_digest(candidate, digest)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Verified against for unknown usernames, so failed logins cost the same either way (timing safety)."""
    return hash_password(secrets.token_hex(8))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def user_bank_id(user_id: str) -> str:
    return f"{get_settings().hindsight_bank_id}-u-{user_id}"


def username_exists(username: str) -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None


def _insert_user(conn: sqlite3.Connection, username: str, password: str, bank_id: str | None = None) -> User:
    user_id = uuid.uuid4().hex
    bank = bank_id or user_bank_id(user_id)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, hindsight_bank_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, hash_password(password), bank, now_iso()),
    )
    return User(user_id, username, bank)


def create_user(username: str, password: str) -> User | None:
    """Returns None if the username is taken. Blocking (PBKDF2): call from a worker thread."""
    try:
        with connect() as conn:
            return _insert_user(conn, username, password)
    except sqlite3.IntegrityError:
        return None


def authenticate(username: str, password: str) -> User | None:
    """Blocking (PBKDF2): call from a worker thread."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    ok = verify_password(password, row["password_hash"] if row else _dummy_hash())
    if row is None or not ok:
        return None
    return User(row["id"], row["username"], row["hindsight_bank_id"])


def create_session(user: User) -> str:
    """Returns a new bearer token. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + timedelta(hours=get_settings().session_ttl_hours)
    with connect() as conn:
        conn.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (hash_token(token), user.id, now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")),
        )
    return token


def delete_session(token: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (hash_token(token),))


def user_for_token(token: str) -> User | None:
    with connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.hindsight_bank_id FROM auth_sessions s
               JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?""",
            (hash_token(token), now_iso()),
        ).fetchone()
    return User(row["id"], row["username"], row["hindsight_bank_id"]) if row else None


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    """FastAPI dependency (sync: runs in the threadpool, so SQLite never blocks the event loop)."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = user_for_token(creds.credentials)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")
    return user


def migrate_legacy_demo_user() -> None:
    """One-time migration from the single-demo-login version of the app.

    Incidents created before isolation existed have created_by=<DEMO_USERNAME> and no user_id,
    and their memories live in the original bank HINDSIGHT_BANK_ID, written only by that account.
    Turn that account into a real user who owns those incidents and that bank. Nothing is deleted.
    Requires DEMO_PASSWORD to be set explicitly if the account does not exist yet.
    """
    s = get_settings()
    with connect() as conn:
        legacy = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE user_id IS NULL AND created_by = ?", (s.demo_username,)
        ).fetchone()[0]
        if not legacy:
            return
        row = conn.execute("SELECT id FROM users WHERE username = ?", (s.demo_username,)).fetchone()
        if row is None:
            bank_taken = conn.execute("SELECT 1 FROM users WHERE hindsight_bank_id = ?", (s.hindsight_bank_id,)).fetchone()
            if bank_taken or not s.demo_password:
                return
            user_id = _insert_user(conn, s.demo_username, s.demo_password, bank_id=s.hindsight_bank_id).id
        else:
            user_id = row["id"]
        conn.execute(
            "UPDATE incidents SET user_id = ? WHERE user_id IS NULL AND created_by = ?", (user_id, s.demo_username)
        )
        log.info("Migrated %d legacy incidents to user '%s'", legacy, s.demo_username)
