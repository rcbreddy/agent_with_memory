"""Learns stable, long-term response preferences from the user's instructions.

- Explicit lasting preferences ("always ...", "end every summary with OK", "from now on ...")
  are added (or replace an existing preference with the same key) immediately.
- Explicit cancellations ("stop ending summaries with OK") remove the stored preference.
- One-off style requests ("be brief this time") are NOT stored as preferences; they are counted
  as candidates and promoted to a learned preference only after PROMOTE_AFTER separate reports.
"""

import logging
import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.groq.client import GroqError, chat_json
from app.hindsight.client import HindsightError
from app.hindsight.preferences import (
    PROMOTE_AFTER,
    Candidate,
    Preference,
    PreferenceProfile,
    load_profile,
    profile_as_json,
    profile_lock,
    save_profile,
)
from app.redaction import redact
from app.schemas import PreferenceChange

log = logging.getLogger(__name__)

CATEGORIES = {"explanation_style", "detail_level", "response_format", "language", "formatting", "other"}

SYSTEM_PROMPT = f"""You maintain an incident-response assistant's memory of ONE user's long-term response preferences.
Given the user's current preference profile and the instruction the user wrote with their latest
report, decide how the profile must change. Preferences are about HOW responses are written:
explanation style, level of technical detail, response format, language, recurring formatting.
Operational/technical facts about systems are NOT preferences.

Rules:
- "add": the user explicitly states a lasting preference, e.g. "always ...", "every summary ...",
  "from now on ...", "in future ...", "I prefer ...", "end every summary with OK", "respond in Spanish".
- "update": the user changes an existing preference -> reuse that preference's key.
- "remove": the user cancels an existing preference, e.g. "stop ending summaries with OK",
  "no need to ... anymore" -> use the existing key.
- "one_time_requests": style requests that apply only to this report or are not stated as lasting,
  e.g. "be brief", "keep it short this time", "use bullet points here". Reuse an existing candidate's
  key when it is the same request, so repeated requests can be recognised. Write their "preference"
  in the general form it would take as a lasting rule, without "this time"/"here"
  (e.g. "Keep responses brief."), because it becomes permanent if the user keeps asking for it.
- Ignore requests about the incident content itself (e.g. "focus on Redis").
- Never include secrets or personal data. Keep each preference one short imperative sentence
  that is directly followable, preserving exact wording such as literal text to append.
- key: a short stable kebab-case slug describing WHAT the preference controls (e.g. "summary-ending",
  "response-language", "detail-level"), so a later change to the same aspect reuses the same key.
- category: one of {sorted(CATEGORIES)}.

Respond with a JSON object:
{{
  "changes": [{{"action": "add"|"update"|"remove", "key": string, "preference": string, "category": string}}],
  "one_time_requests": [{{"key": string, "preference": string, "category": string}}],
  "reason": string
}}"""


class _Item(BaseModel):
    action: str = "add"
    key: str
    preference: str = ""
    category: str = "other"

    @field_validator("key", mode="before")
    @classmethod
    def slug(cls, v: object) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", str(v or "").lower()).strip("-")[:60]
        if not s:
            raise ValueError("empty key")
        return s

    @field_validator("category", mode="before")
    @classmethod
    def known_category(cls, v: object) -> str:
        return v if v in CATEGORIES else "other"


class _Decision(BaseModel):
    changes: list[_Item] = Field(default_factory=list)
    one_time_requests: list[_Item] = Field(default_factory=list)
    reason: str = ""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def apply_decision(profile: PreferenceProfile, decision: _Decision) -> list[PreferenceChange]:
    """Mutates profile; returns the user-visible changes."""
    changes: list[PreferenceChange] = []
    prefs = {p.key: p for p in profile.preferences}
    cands = {c.key: c for c in profile.candidates}

    for item in decision.changes:
        if item.action == "remove":
            removed = prefs.pop(item.key, None)
            cands.pop(item.key, None)
            if removed:
                changes.append(PreferenceChange(action="removed", key=item.key, preference=removed.preference))
            continue
        text = redact(item.preference)[:300]
        if item.action not in {"add", "update"} or not text:
            continue  # unknown action from the model: ignore rather than guess
        old = prefs.get(item.key)
        if old and old.preference == text:
            continue
        prefs[item.key] = Preference(key=item.key, preference=text, category=item.category, source="explicit", since=_now())
        cands.pop(item.key, None)
        changes.append(PreferenceChange(action="updated" if old else "added", key=item.key, preference=text))

    for item in decision.one_time_requests:
        text = redact(item.preference)[:300]
        if not text or item.key in prefs:
            continue
        cand = cands.get(item.key)
        if cand:
            cand.count += 1
        else:
            cand = cands[item.key] = Candidate(key=item.key, preference=text, category=item.category)
        if cand.count >= PROMOTE_AFTER:
            prefs[item.key] = Preference(key=item.key, preference=cand.preference, category=cand.category, source="learned", since=_now())
            cands.pop(item.key)
            changes.append(PreferenceChange(action="learned", key=item.key, preference=cand.preference))

    profile.preferences = list(prefs.values())
    profile.candidates = sorted(cands.values(), key=lambda c: -c.count)[:20]
    return changes


async def learn_preferences(bank_id: str, instruction: str) -> tuple[list[PreferenceChange], str | None]:
    """Update the stored profile from this report's instruction. Returns (changes, error)."""
    if not instruction.strip():
        return [], None  # nothing new was said; stored preferences stay as they are
    async with profile_lock(bank_id):
        try:
            profile = await load_profile(bank_id)
            result = await chat_json(
                SYSTEM_PROMPT,
                f"CURRENT PROFILE:\n{profile_as_json(profile)}\n\n"
                f"USER INSTRUCTION WITH THIS REPORT:\n{instruction}\n\nReturn only the JSON object.",
                reasoning_effort=get_settings().groq_aux_reasoning_effort,
            )
            decision = _Decision.model_validate(result.data)
        except (GroqError, HindsightError, ValidationError) as exc:
            log.warning("Preference learning failed: %s", type(exc).__name__)
            return [], "preference learning failed; stored preferences are unchanged"

        before = profile.model_dump(exclude={"updated_at"})
        changes = apply_decision(profile, decision)
        if profile.model_dump(exclude={"updated_at"}) == before:
            return [], None
        try:
            await save_profile(bank_id, profile)
        except HindsightError as exc:
            return [], str(exc)
        log.info("Preference profile updated: %s", [f"{c.action}:{c.key}" for c in changes])
        return changes, None
