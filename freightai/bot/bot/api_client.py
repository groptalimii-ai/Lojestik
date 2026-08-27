"""
Backend client.

CHANGED: every call used to carry `X-User-Id: <raw telegram id>`, which
the backend trusted at face value -- any client could set that header to
any value and rate-limit (or act) as someone else. Calls now carry a real
`Authorization: Bearer <JWT>`, obtained by first calling /auth/telegram
with an HMAC signature only this bot process can produce (see
_get_token()). The backend verifies the signature, not the claimed id.
"""
import hashlib
import hmac
import time

import httpx

from bot.config import BACKEND_URL, BOT_SERVICE_SECRET


class RateLimitExceeded(Exception):
    """Raised when the backend returns 429 - daily limit reached for this user."""
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class BackendClient:
    def __init__(self):
        self._client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=30)
        # In-memory per-process token cache: {telegram_id: (token, expires_at_epoch)}.
        # A dict is fine for a single bot instance with MemoryStorage; if the
        # bot is ever scaled to multiple workers, move this to Redis.
        self._tokens: dict[str, tuple[str, float]] = {}

    def _sign(self, telegram_id: str) -> tuple[str, str]:
        timestamp = str(int(time.time()))
        message = f"{telegram_id}:{timestamp}".encode()
        signature = hmac.new(BOT_SERVICE_SECRET.encode(), message, hashlib.sha256).hexdigest()
        return timestamp, signature

    async def _get_token(self, telegram_user_id: int | str, full_name: str | None = None) -> str:
        telegram_id = str(telegram_user_id)
        cached = self._tokens.get(telegram_id)
        if cached and cached[1] > time.time() + 30:  # 30s safety margin
            return cached[0]

        timestamp, signature = self._sign(telegram_id)
        r = await self._client.post(
            "/auth/telegram",
            json={
                "telegram_id": telegram_id,
                "timestamp": timestamp,
                "signature": signature,
                "full_name": full_name,
            },
        )
        r.raise_for_status()
        data = r.json()
        token = data["access_token"]
        # Matches backend JWT_EXPIRE_MINUTES; a slightly-early local expiry
        # is harmless, it just triggers one extra /auth/telegram call.
        self._tokens[telegram_id] = (token, time.time() + 60 * 60)
        return token

    async def _auth_headers(self, telegram_user_id: int | str, force_refresh: bool = False) -> dict:
        if force_refresh:
            self._tokens.pop(str(telegram_user_id), None)
        token = await self._get_token(telegram_user_id)
        return {"Authorization": f"Bearer {token}"}

    async def _post(self, path: str, telegram_user_id: int | str, json: dict | None = None) -> dict:
        headers = await self._auth_headers(telegram_user_id)
        r = await self._client.post(path, json=json, headers=headers)
        if r.status_code == 401:
            # The cached token was rejected -- most likely revoked
            # server-side (e.g. scripts/promote_admin.py just ran, or an
            # explicit /auth/logout happened elsewhere). Get a genuinely
            # fresh token and retry ONCE, transparently, instead of
            # surfacing a confusing "server error (401)" to the user for
            # something the bot can self-heal.
            headers = await self._auth_headers(telegram_user_id, force_refresh=True)
            r = await self._client.post(path, json=json, headers=headers)
        if r.status_code == 429:
            raise RateLimitExceeded(r.json().get("detail", "تم تجاوز الحد اليومي المسموح."))
        r.raise_for_status()
        return r.json()

    async def _get(self, path: str, telegram_user_id: int | str) -> dict | list:
        headers = await self._auth_headers(telegram_user_id)
        r = await self._client.get(path, headers=headers)
        if r.status_code == 401:
            headers = await self._auth_headers(telegram_user_id, force_refresh=True)
            r = await self._client.get(path, headers=headers)
        r.raise_for_status()
        return r.json()

    async def logout(self, telegram_user_id: int | str) -> None:
        """Revokes the current cached token server-side and drops it
        locally -- the next call will mint a fresh one."""
        telegram_id = str(telegram_user_id)
        cached = self._tokens.get(telegram_id)
        if cached:
            try:
                await self._client.post(
                    "/auth/logout", headers={"Authorization": f"Bearer {cached[0]}"}
                )
            except Exception:
                pass  # best-effort -- local cache eviction below still happens
        self._tokens.pop(telegram_id, None)

    async def extract_load(self, text: str, telegram_user_id: int | str) -> dict:
        return await self._post("/ai/extract-load", telegram_user_id, {"text": text})

    async def create_load(self, payload: dict, telegram_user_id: int | str) -> dict:
        return await self._post("/loads", telegram_user_id, payload)

    async def find_matches(self, load_id: str, telegram_user_id: int | str) -> list[dict]:
        return await self._post(f"/loads/{load_id}/matches", telegram_user_id)

    async def register_carrier(self, payload: dict, telegram_user_id: int | str) -> dict:
        return await self._post("/carriers", telegram_user_id, payload)

    async def get_carrier_by_phone(self, phone: str, telegram_user_id: int | str) -> dict | None:
        try:
            return await self._get(f"/carriers/by-phone/{phone}", telegram_user_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def add_truck(self, payload: dict, telegram_user_id: int | str) -> dict:
        return await self._post("/carriers/trucks", telegram_user_id, payload)

    async def list_carrier_trucks(self, carrier_id: str, telegram_user_id: int | str) -> list[dict]:
        return await self._get(f"/carriers/{carrier_id}/trucks", telegram_user_id)

    async def dashboard(self, telegram_user_id: int | str) -> dict:
        return await self._get("/analytics/dashboard", telegram_user_id)

    async def request_pricing(self, payload: dict, telegram_user_id: int | str) -> dict:
        return await self._post("/pricing/request", telegram_user_id, payload)

    async def submit_intake(self, text: str, telegram_user_id: int | str) -> dict:
        return await self._post("/intake/message", telegram_user_id, {"text": text})


backend = BackendClient()
