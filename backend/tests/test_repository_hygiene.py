"""Secret hygiene of the repository itself: no credential-shaped literals and no sensitive files are
tracked by git. Credentials belong in environment variables (backend/.env locally, the host's
environment in production); backend/.env.example holds placeholders only."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# High-confidence patterns only, so a hit is always worth a look.
CREDENTIAL_PATTERNS = {
    "connection string with inline credentials": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"{}()]+:[^\s@/'\"{}()]+@"),
    "provider API token": re.compile(r"\b(?:gsk|ghp|gho|github_pat|xox[abprs])_[A-Za-z0-9_]{20,}"),
    "secret key (sk-...)": re.compile(r"\bsk-[A-Za-z0-9-]{20,}"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "JSON web token": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}
SENSITIVE_FILE = re.compile(
    r"(^|/)(\.env(\.(?!example$)[^/]+)?|[^/]+\.(db|sqlite3?|pem|key|p12|pfx)|id_(rsa|ed25519|ecdsa)[^/]*|\.ollama/.*)$"
)


def _tracked_files() -> list[str]:
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    # Fixed argument list, no user input.
    out = subprocess.run([git, "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True).stdout  # noqa: S603
    return [p for p in out.decode().split("\0") if p]


def test_no_sensitive_files_are_tracked():
    tracked = _tracked_files()
    assert "backend/.env.example" in tracked  # placeholders only, documented setup
    assert [p for p in tracked if SENSITIVE_FILE.search(p)] == []


def test_no_credential_literals_in_tracked_files():
    findings = []
    for rel in _tracked_files():
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # binary or deleted in the working tree
        for label, pattern in CREDENTIAL_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{rel}:{line}: {label}")  # location only, never the value
    assert findings == []


def test_env_example_contains_placeholders_only():
    example = (REPO_ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1) for line in example.splitlines() if "=" in line and not line.lstrip().startswith("#")
    )
    for key in ("GROQ_API_KEY", "HINDSIGHT_API_KEY", "DEMO_PASSWORD"):
        assert values.get(key, "").strip() == "", f"{key} must be empty in .env.example"
