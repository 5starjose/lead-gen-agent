import os
from functools import lru_cache

class Settings:
    def __init__(self):
        self.app_env = os.getenv("APP_ENV", "development")  # development|test|production
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./leadgen.db")
        # Render/Heroku style postgres:// -> postgresql+psycopg://
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.admin_password = os.getenv("ADMIN_PASSWORD", "")
        self.api_token = os.getenv("API_TOKEN", "") or self.admin_password
        self.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")
        self.google_places_api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
        self.yelp_api_key = os.getenv("YELP_API_KEY", "")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.llm_provider = os.getenv("LLM_PROVIDER", "")  # optional, not required
        self.notification_email = os.getenv("NOTIFICATION_EMAIL", "")
        self.smtp_url = os.getenv("SMTP_URL", "")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.allow_synthetic = os.getenv("ALLOW_SYNTHETIC_PROVIDER", "") == "1" or self.app_env == "test"
        self.default_timezone = os.getenv("DEFAULT_TIMEZONE", "America/Los_Angeles")

    @property
    def synthetic_allowed(self):
        # Hard env separation: synthetic only in test, never in production live runs
        return self.app_env == "test" and self.allow_synthetic

@lru_cache
def get_settings():
    return Settings()
