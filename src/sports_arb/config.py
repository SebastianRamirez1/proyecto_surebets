from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    the_odds_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    odds_provider: str = "mock"
    min_profit_margin: float = 0.01
    total_stake: float = 1000.0
    scan_interval: int = 60
    sports: str = "soccer,tennis"

    @property
    def sports_list(self) -> list[str]:
        return [s.strip() for s in self.sports.split(",") if s.strip()]


settings = Settings()
