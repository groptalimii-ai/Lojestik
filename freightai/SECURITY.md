# Security

This document states what's actually true about this codebase's security
posture -- covered and not covered -- rather than a generic checklist.
Update it whenever a security-relevant change lands; a stale security doc
is worse than none, because it's actively misleading.

## Identity & authentication

- End users never authenticate directly. Telegram vouches for
  `from_user.id` to the bot process; the bot proves to the backend that a
  login request genuinely came from it (not an arbitrary client claiming
  a `telegram_id`) via an HMAC-SHA256 signature over
  `{telegram_id}:{timestamp}`, keyed with `BOT_SERVICE_SECRET` (shared
  only between the bot and backend, never exposed to users). See
  `backend/app/core/security.py::verify_bot_signature`.
- A 60-second timestamp window on that signature blocks replay of a
  captured `/auth/telegram` request.
- The backend then issues a short-lived JWT (`JWT_EXPIRE_MINUTES`,
  default 24h), signed with `JWT_SECRET` (HS256). This JWT is **signed,
  not encrypted** -- anyone can decode and read its payload (user id,
  role, issue time); they cannot forge or alter it without the secret.
  Do not put anything in the JWT payload that shouldn't be readable by
  whoever holds the token.
- Every mutating/identity-sensitive endpoint depends on
  `core/deps.py::get_current_user`, which derives identity from the JWT
  -- never from a client-supplied header or request body field. This
  closes what was originally a real vulnerability (an `X-User-Id` header
  the client could set to any value).
- **Revocation**: `POST /auth/logout` revokes one specific token
  immediately (Redis blacklist, keyed by the token's `jti`, TTL matched
  to the token's own remaining lifetime). `scripts/promote_admin.py`
  additionally invalidates *every* existing token for the promoted user
  (`User.tokens_valid_after`), so a role change takes effect immediately
  instead of waiting for natural token expiry.

## Authorization

- Admin-only actions (`GET /analytics/dashboard`, deal status changes
  requiring approval, `POST /intake/message`) are gated by
  `core/deps.py::require_admin`, which reads `User.role` from the
  database -- never from a client-supplied flag. There is deliberately
  **no API endpoint that can promote an account to admin** -- only
  `scripts/promote_admin.py`, run with direct database access, can do
  that. A self-promotion endpoint would be a privilege-escalation hole by
  construction.
- Resource ownership is checked where it matters (e.g. `POST
  /carriers/trucks` verifies the caller owns the target `carrier_id`
  before allowing a truck to be added to it).

## Input handling

- All database queries go through SQLAlchemy's ORM with parameterized
  queries. There is no raw SQL string concatenation anywhere in this
  codebase -- SQL injection is not a realistic risk here as currently
  written.
- Pydantic schemas (`schemas.py`, `pricing_schemas.py`,
  `leads_schemas.py`) enforce length/range bounds on every
  client-supplied field reaching a mutating endpoint.
- AI-extracted fields (Claude's output, not the client's direct input)
  are a separate concern -- see "AI-specific risks" below.

## AI-specific risks

- User-supplied free text is sent to Claude for structured extraction
  (`services/extraction.py`, `services/lead_extraction.py`). This text is
  **not sanitized against prompt injection** -- a message could attempt
  to manipulate the model's output. The actual blast radius is limited:
  extraction output is constrained to specific JSON fields (never
  free-form text that gets executed or rendered), and is bounded/
  truncated before storage (`api/intake.py::_bounded`,
  `MAX_EXTRACTED_STR_LEN`). Worst realistic case is bad data in those
  fields, not code execution or data exfiltration.
- Extraction confidence is tracked and surfaced: `Load.extraction_confidence`
  is shown to the shipper before they confirm a load
  (`bot/handlers/newload.py`); `CarrierLead.needs_review` /
  `LoadLead.needs_review` are set automatically when the AI's
  self-reported confidence is below `LOW_CONFIDENCE_THRESHOLD` (0.6).
  This is a **mitigation, not a guarantee** -- a confident-sounding
  hallucination can still slip through. There is no automated
  fact-checking of extracted data against ground truth.
- Transient AI API failures are retried with backoff
  (`services/ai_retry.py`) and don't consume the caller's daily quota if
  they ultimately fail (`services/rate_limit.py::refund_user_rate_limit`).

## Rate limiting

- Every quota-bearing endpoint is limited per-day, per-authenticated-user
  (keyed on the JWT's `sub`, not a client-supplied identifier), via
  Redis with automatic UTC-midnight reset. See `services/rate_limit.py`
  and the README's "Rate Limiting" section for current per-scope limits.
- `/auth/telegram` itself is **not** rate-limited. It doesn't need to be
  for correctness (the HMAC signature can't be brute-forced in any
  practical sense), but a flood of invalid requests against it would
  still cost CPU/DB load. Acceptable at current scale; worth revisiting
  if this ever sits behind a public, high-traffic surface.

## Data integrity under concurrency

- `Location.city_name`, `Company.contact_phone`, and `CarrierProfile.phone`
  have database-level unique constraints. Get-or-create logic against
  these tables uses `services/db_utils.py::get_or_create`, which handles
  the race window (two concurrent requests resolving the same city/phone
  simultaneously) via a SAVEPOINT and conflict recovery, instead of
  either crashing or silently duplicating.
- `Company` matching by name only (when no phone is available) is **not**
  race-protected -- deliberately, since company display names are not
  unique identifiers in reality (multiple real companies can share a
  name), so no uniqueness constraint would be correct there.

## Explicitly out of scope for this codebase

These are real, legitimate concerns -- just not things application code
controls:

- **TLS/HTTPS termination** -- the responsibility of whatever platform
  this is deployed on (Render/Railway/Fly typically provide it
  automatically). This codebase does not set `Strict-Transport-Security`
  itself, to avoid falsely implying it controls something it doesn't.
- **Encryption at rest** -- provided by the database host (Supabase)
  at the infrastructure level.
- **Secrets management** -- currently `.env` files / platform environment
  variables. No secrets manager (Vault, AWS Secrets Manager) integration.
  Adequate for current scale; revisit if the team or attack surface
  grows.

## Known, accepted gaps (see README "Known Gaps" for the full list)

- No automated penetration testing has been performed.
- No dependency vulnerability scanning existed until this pass added
  `pip-audit` to CI (`.github/workflows/ci.yml`, weekly + every push/PR)
  and Dependabot (`.github/dependabot.yml`, weekly PRs).
- This document, and the codebase's security measures generally, have
  been produced through careful code review, not through running the
  application against a real deployment or a live penetration test.
  **Verify independently before relying on any of this for a real
  production launch with real user data.**

## Reporting a concern

This is a small, single-operator project without a dedicated security
contact process yet. If you find a genuine vulnerability, the practical
step right now is: don't publish it publicly, fix it directly if you can,
and treat this file as the place to record what changed and why.
