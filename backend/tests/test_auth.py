"""Authentication, sessions and authorization."""

import sqlite3

import pytest

from app.config import get_settings
from tests.conftest import DEMO_1, register

PROTECTED = [
    ("get", "/api/auth/me"),
    ("get", "/api/incidents"),
    ("post", "/api/incidents/analyze"),
    ("get", "/api/incidents/INC-00000000"),
    ("post", "/api/incidents/INC-00000000/resolve"),
    ("get", "/api/incidents/INC-00000000/learning"),
    ("get", "/api/incidents/INC-00000000/memories"),
]


def test_register_then_login(client):
    register(client, "alice", "correct-horse-1")
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "correct-horse-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice" and body["token"] and body["user_id"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.json()["username"] == "alice"


def test_username_is_case_insensitive_and_unique(client):
    register(client, "alice")
    assert client.post("/api/auth/register", json={"username": "ALICE", "password": "another-pass-9"}).status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "al", "password": "long-enough-1"},  # username too short
        {"username": "alice", "password": "short"},  # password too short
        {"username": "bad name!", "password": "long-enough-1"},  # invalid characters
        {"username": "alice"},  # missing field
    ],
)
def test_register_rejects_invalid_input(client, payload):
    assert client.post("/api/auth/register", json=payload).status_code == 422


def test_invalid_login_does_not_reveal_which_part_was_wrong(client):
    register(client, "alice", "correct-horse-1")
    wrong_password = client.post("/api/auth/login", json={"username": "alice", "password": "nope-nope"})
    unknown_user = client.post("/api/auth/login", json={"username": "mallory", "password": "nope-nope"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_endpoints_require_a_session(client, method, path):
    kwargs = {"json": DEMO_1} if method == "post" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    bogus = getattr(client, method)(path, headers={"Authorization": "Bearer not-a-real-token"}, **kwargs)
    assert bogus.status_code == 401


def test_logout_invalidates_the_token(client):
    headers = register(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/incidents", headers=headers).status_code == 401


def test_tokens_are_stored_hashed(client):
    headers = register(client)
    token = headers["Authorization"].split()[1]
    with sqlite3.connect(get_settings().database_path) as conn:
        stored = [r[0] for r in conn.execute("SELECT token_hash FROM auth_sessions")]
    assert stored and token not in stored and all(len(h) == 64 for h in stored)


def test_expired_session_is_rejected(client, monkeypatch):
    monkeypatch.setenv("SESSION_TTL_HOURS", "0")
    get_settings.cache_clear()
    headers = register(client)
    assert client.get("/api/incidents", headers=headers).status_code == 401


def test_register_creates_private_bank(client, fake_hindsight):
    headers = register(client)
    user_id = client.get("/api/auth/me", headers=headers).json()["user_id"]
    assert ("acreate_bank", f"{get_settings().hindsight_bank_id}-u-{user_id}") in fake_hindsight.calls
