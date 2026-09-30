"""Secret and personal-data redaction, applied to everything that can become long-term memory
(Hindsight) and, as defense in depth, to log records."""

import re

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED_KEY]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (
        re.compile(
            r"(?i)([\"']?\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
            r"client[_-]?secret|private[_-]?key|auth)\b[\"']?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\b(?:sk|gsk|ghp|gho|github_pat|xox[abprs]|hsk)[-_][A-Za-z0-9_-]{16,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@"), r"\1[REDACTED]@"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_NUMBER]"),
]


def redact(text: str) -> str:
    """Remove credentials, tokens, keys, JWTs, e-mail addresses and card-like numbers."""
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text.strip()


def redact_values(text: str, values: list[str]) -> str:
    """Remove exact known secret values (e.g. the configured API keys)."""
    for v in values:
        if v and v in text:
            text = text.replace(v, "[REDACTED_SECRET]")
    return text
