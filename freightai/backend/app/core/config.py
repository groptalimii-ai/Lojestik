"""
Central configuration. Every secret is loaded from environment variables.
NEVER hardcode tokens, keys, or passwords here.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    # A placeholder default (NOT used in real deployment -- production
    # always sets DATABASE_URL explicitly) so pure-logic test files that
    # only import app.services.* (no real DB connectivity needed) don't
    # crash on `Settings()` construction just because no .env is present.
    # SQLAlchemy engines are lazy -- create_async_engine() with a bogus
    # URL never actually connects until a query runs.
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/freightai_dev"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Telegram
    telegram_bot_token: str = ""
    telegram_admin_chat_id: str = ""

    # AI
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-4-6"

    # Auth
    jwt_secret: str = "insecure-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    # Shared secret between the bot process and this backend ONLY.
    # Never exposed to Telegram users. Proves a /auth/telegram request
    # genuinely originated from our bot, not from an arbitrary client
    # spoofing a telegram_id.
    bot_service_secret: str = "insecure-dev-bot-secret-change-me"

    # Business
    capital_target_sar: float = 80000.0

    # Rate limiting (per user, per day)
    rate_limit_ai_extract_per_day: int = 30
    rate_limit_loads_per_day: int = 20
    rate_limit_carrier_actions_per_day: int = 20
    rate_limit_default_per_day: int = 100
    rate_limit_pricing_per_day: int = 5
    # Cost-safety ceiling, not a UX limit -- the whole point of /intake is
    # high-volume manual entry by the operator. This just guards against a
    # runaway loop/script racking up Anthropic API cost unattended.
    rate_limit_intake_per_day: int = 1000

    # Google Maps -- FROZEN until commercial launch. See README "Google
    # Maps Integration". False by default so this NEVER calls Google or
    # requires billing, no matter what's in google_maps_api_key. Flip
    # deliberately, not accidentally, when the free (Haversine + static
    # city table) accuracy stops being good enough.
    google_maps_enabled: bool = False
    google_maps_api_key: str = ""

    environment: str = "development"


settings = Settings()

if settings.environment == "production":
    _insecure_defaults = {
        "jwt_secret": "insecure-dev-secret-change-me",
        "bot_service_secret": "insecure-dev-bot-secret-change-me",
    }
    for _field, _default in _insecure_defaults.items():
        if getattr(settings, _field) == _default:
            raise RuntimeError(
                f"settings.{_field} is still the insecure default. "
                "Set a real secret via environment variable before running in production."
            )
