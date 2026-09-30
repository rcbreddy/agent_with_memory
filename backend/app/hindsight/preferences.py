"""Long-term user preference memory, stored in the user's own Hindsight bank.

The user's active preferences live in ONE Hindsight document (PROFILE_DOCUMENT_ID) that is
rewritten with update_mode="replace" whenever a preference is added, changed or cancelled.
So a cancelled preference is removed from memory instead of lingering next to its replacement.

- load_profile(): fetch the profile document (documents API: get_document) before every response
- save_profile(): retain the updated profile (aretain, document_id + update_mode="replace")
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from hindsight_client_api.exceptions import NotFoundException
from pydantic import BaseModel, Field, ValidationError

from app.hindsight.client import HindsightError, describe_error, ensure_bank, get_client

log = logging.getLogger(__name__)

PROFILE_DOCUMENT_ID = "user-preference-profile"
PREFERENCE_TAG = "kind:user-preference"
# A repeated one-off style request becomes a lasting preference after this many separate reports.
PROMOTE_AFTER = 3


class Preference(BaseModel):
    key: str  # stable slug, e.g. "summary-ending"; a new value for the same key replaces the old one
    preference: str  # the instruction to follow, e.g. "End every summary with 'OK'."
    category: str = "other"
    source: str = "explicit"  # "explicit" (user stated it) | "learned" (repeated behaviour)
    since: str = ""


class Candidate(BaseModel):
    key: str
    preference: str
    category: str = "other"
    count: int = 1


class PreferenceProfile(BaseModel):
    preferences: list[Preference] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    updated_at: str = ""


# One lock per bank so concurrent requests from the same user don't lose each other's updates.
_locks: dict[str, asyncio.Lock] = {}


def profile_lock(bank_id: str) -> asyncio.Lock:
    return _locks.setdefault(bank_id, asyncio.Lock())


async def load_profile(bank_id: str) -> PreferenceProfile:
    """Read the user's preference profile from Hindsight. Missing profile = no preferences yet."""
    try:
        await ensure_bank(bank_id)
        doc = await get_client().documents.get_document(bank_id=bank_id, document_id=PROFILE_DOCUMENT_ID)
    except NotFoundException:
        return PreferenceProfile()
    except Exception as exc:
        raise HindsightError(f"could not load preferences from Hindsight ({describe_error(exc)})") from exc
    raw = (doc.document_metadata or {}).get("profile")
    try:
        return PreferenceProfile.model_validate_json(raw) if raw else PreferenceProfile()
    except ValidationError:
        log.warning("Unreadable preference profile in bank %s; starting fresh", bank_id)
        return PreferenceProfile()


def render_profile(profile: PreferenceProfile) -> str:
    """Natural-language version retained in Hindsight (so the preferences are also recallable facts)."""
    if not profile.preferences:
        return "The user currently has no active long-term response preferences."
    lines = ["The user's current long-term response preferences (apply to every response):"]
    lines += [f"- ({p.category}) {p.preference}" for p in profile.preferences]
    return "\n".join(lines)


async def save_profile(bank_id: str, profile: PreferenceProfile) -> None:
    """Replace the user's profile document in Hindsight. Raises HindsightError."""
    now = datetime.now(UTC)
    profile.updated_at = now.isoformat(timespec="seconds")
    try:
        await ensure_bank(bank_id)
        resp = await get_client().aretain(
            bank_id=bank_id,
            content=render_profile(profile),
            context="the user's current long-term response preferences; this replaces any earlier list",
            document_id=PROFILE_DOCUMENT_ID,
            update_mode="replace",  # cancelled/changed preferences disappear from memory
            timestamp=now,
            metadata={"profile": profile.model_dump_json(), "memory_source": "user-preferences"},
            tags=[PREFERENCE_TAG],
            # Wait for storage so the very next report sees the new preferences.
            retain_async=False,
        )
    except Exception as exc:
        log.warning("Saving preference profile failed: %s", describe_error(exc))
        raise HindsightError(f"could not save preferences to Hindsight ({describe_error(exc)})") from exc
    if not resp.success:
        raise HindsightError("Hindsight retain returned success=false")


def profile_as_json(profile: PreferenceProfile) -> str:
    return json.dumps(
        {
            "preferences": [{"key": p.key, "preference": p.preference, "category": p.category} for p in profile.preferences],
            "candidates": [{"key": c.key, "preference": c.preference, "count": c.count} for c in profile.candidates],
        },
        ensure_ascii=False,
    )
