# Repository Audit — AI Incident Response Agent

Audit of commit `10a5368` (before optimization). Severity: **CRITICAL / HIGH / MEDIUM / LOW**.
Secret values found during the audit are never reproduced here.

## A. Current architecture

```text
React (Vite, TS, Tailwind)  ──fetch──▶  FastAPI
                                          │ /api/incidents/analyze
                                          ├─ asyncio.gather(Hindsight recall, preference profile load)
                                          ├─ Groq analysis (JSON mode, Pydantic-validated, 1 retry)
                                          ├─ asyncio.gather(
                                          │     memory extraction (Groq) → Hindsight retain (unconfirmed),
                                          │     preference learning (Hindsight load → Groq → Hindsight save))
                                          └─ SQLite insert → response
                                          │ /api/incidents/{id}/resolve
                                          └─ Hindsight retain (confirmed, document_id = incident id) → SQLite update
```

* Hindsight (official `hindsight-client`) is the only agent memory; one private bank per user.
* SQLite stores users (PBKDF2 hashes), bearer sessions and the incident list/history.
* Groq is called with raw `httpx`.

## B. Strengths

* Hindsight is genuinely the memory layer; SQLite is never read as "memory".
* Per-user banks (`<prefix>-u-<user_id>`); every SQL query filters by `user_id`; foreign incidents return 404.
* Parameterized SQL everywhere; Pydantic input validation with length limits.
* Confirmed vs auto-extracted knowledge is already tracked (`memory_source` metadata).
* Memory extractor redacts secrets and skips verbatim duplicates; temporary style instructions are
  counted as candidates rather than stored (promotion after 3 reports).
* Groq output validated by Pydantic; invented `historical_matches` are dropped when recall was empty.
* Recall failure degrades gracefully ("analysis uses the current incident only").

## C. Weaknesses / issues (with severity)

| ID | Sev | Area | Issue |
|---|---|---|---|
| S1 | **CRITICAL** | Security | `backend/incidents.db` is tracked in git: 11 users' password hashes, **11 plaintext bearer session tokens** (no expiry) and 40 incidents' content. If the Render service was deployed from the repo, these tokens may be valid in production. |
| T1 | **CRITICAL** | Testing | No automated tests of any kind (backend or frontend). No CI. |
| L1 | HIGH | Latency | Analyze response waits for **memory extraction (a second Groq call) + Hindsight retain** even though the user doesn't need them to read the analysis. |
| L2 | HIGH | Latency | Preference learning (Hindsight load + Groq + Hindsight save) runs *after* the analysis although it doesn't depend on it. |
| L3 | HIGH | Latency | A new `httpx.AsyncClient` (new TCP+TLS handshake) is created for every Groq call. |
| L4 | HIGH | Latency/resilience | Hindsight recall has a 60 s timeout × 2 attempts on the critical path; no recall-specific budget. |
| S2 | HIGH | Security | Confirmed-resolution document retains **raw, unredacted** symptoms and error logs in Hindsight (secrets in logs would become long-term memory). |
| S3 | HIGH | Security | Session tokens stored in plaintext and never expire. |
| S4 | HIGH | Security/perf | PBKDF2 (200k iterations) and SQLite run synchronously inside `async def` endpoints → event loop blocked during login/register. |
| P1 | HIGH | Alignment | The LEARN step is invisible: the frontend's `AnalyzeResponse` type omits `memory` and `preferences`; confirmed vs hypothesis status (`confirmed`) is not in the TS type or UI. |
| L5 | MEDIUM | Tokens | Recall `max_tokens=4096`, unlimited recalled incidents × 8 facts each, 10 KB of logs and a duplicated "Return: 1..6" instruction block are all sent to Groq. |
| L6 | MEDIUM | Latency | Concurrent cold-cache `ensure_bank` calls issue duplicate `acreate_bank` requests; login blocks on a Hindsight bank upsert. |
| L7 | MEDIUM | Latency | Public `/api/health` makes a Hindsight network call on every hit (uncached). |
| S5 | MEDIUM | Security | Upstream error bodies (Groq error text, Hindsight exception text) are forwarded to clients. LLM output (may contain incident content) is logged on validation failure. |
| S6 | MEDIUM | Security | Insecure default `DEMO_PASSWORD=admin123`; CORS allows all methods/headers; production URLs hardcoded. |
| S7 | MEDIUM | Security | Incident text is interpolated into prompts with no data/instruction boundary (prompt injection). Isolation limits blast radius to the attacker's own bank. |
| S8 | MEDIUM | Security | Redaction misses quoted JSON secrets (`"api_key": "…"`), `Authorization: Basic …`. |
| Q1 | MEDIUM | Code quality | `preferences.py` imports private `_describe`/`_get_client`; auth routes mix HTTP, hashing, session and migration logic; untyped `dict` responses (`/me`, list, health); status fields are free-form `str`. |
| Q2 | MEDIUM | Code quality | Retry policy inconsistent: validation errors retried, malformed JSON not. |
| M1 | MEDIUM | Memory quality | Same-service memories are always shown regardless of relevance score; ordering ignores confirmation (trust). |
| M2 | MEDIUM | Memory quality | Duplicate detection is exact-string only; near-duplicates are re-stored. |
| F1 | MEDIUM | Frontend bug | `API_BASE` defaults to the production Render URL, so local dev ignores the Vite proxy and hits production. |
| F2 | MEDIUM | Frontend | "Show prompt" has no error/loading handling (unhandled promise). |
| A1 | MEDIUM | Accessibility | Login labels not associated with inputs; errors not announced (`role="alert"`); no `aria-live` for loading; `outline-none` removes focus rings; `text-slate-500`/`600` on `slate-950` fails WCAG AA (≈4:1); workflow stepper status conveyed by colour. |
| D1 | MEDIUM | Docs | `.env.example` is git-ignored (`.env.*`) though the README tells users to copy it; no testing/security/failure/latency docs; no Mermaid diagram. |
| O1 | MEDIUM | Observability | No per-stage timings, no token counts. |
| Q3 | LOW | Code quality | Unused frontend `api.memories` payload fields; `created_by`/`username` duplicated columns (kept for migration compatibility). |
| L8 | LOW | DB | No WAL / busy timeout (needed once background tasks write concurrently). |
| S9 | LOW | Security | No login rate limiting (documented as remaining risk). |

## D. Performance bottlenecks (critical path of `/analyze`, before)

```text
[recall ‖ load prefs] → Groq analysis → [Groq extraction → retain ‖ load prefs → Groq prefs → save prefs] → SQLite → response
                         ^ required      ^^^^^^^^^^^^^^^^^^^^^^^^ not needed for the response ^^^^^^^^^^^^^
```
Two to three LLM round-trips serialized after the analysis, plus a fresh TLS handshake per Groq call.

## E. Security risks
S1–S9 above. No real API keys were found in git history (the two `API_KEY=` matches are README placeholders).
Frontend never calls Groq/Hindsight; `VITE_API_URL` is the only `VITE_*` variable and holds no secret.

## F. Testing gaps
Everything: auth, isolation, analysis failure modes, Hindsight recall/retain, memory loop, preference learning,
redaction, log hygiene, frontend rendering.

## G. Code-quality issues
Q1–Q3, S5 (error handling), F2.

## H. Problem-alignment issues
P1; the UI never states "historical memory is evidence, not the answer"; the learning loop
(RECALL → REASON → LEARN → RETAIN → REUSE) is only partly visible.

## I. Innovation opportunities
Trust-ranked recall (confirmed > hypothesis), richer "why recalled" signals (error signature, recent change),
near-duplicate suppression, visible learning status, token/latency transparency.

## J. Documentation / accessibility gaps
D1, A1.

## Optimization plan (ordered by expected impact)

1. **S1/S3** Untrack `incidents.db`; store only SHA-256 token hashes (invalidates every leaked token); session TTL.
2. **T1** Pytest suite with an in-memory fake Hindsight + Groq mock transport, incl. the end-to-end memory loop; CI.
3. **L1/L2/L3/L4** Move extraction+retain to a background task with persisted, pollable status; run preference
   learning concurrently with the Groq analysis; shared Groq HTTP client; recall time budget.
4. **S2/S5/S7/S8** Redact confirmed-resolution documents; generic upstream errors; injection boundary; stronger redaction; log-redaction filter.
5. **P1/M1/M2** Surface LEARN in the UI; confirmed vs hypothesis labels; trust-weighted ranking; near-duplicate suppression.
6. **L5/L6/L7/O1** Prompt/recall budgets; ensure-bank de-duplication; cached health; stage timings + token usage.
7. **Q1/Q2** Split auth service from routes; typed responses; consistent retry policy.
8. **A1/D1/F1/F2** Accessibility fixes, README rewrite, `.env.example`, dev API base fix.
