from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    the_odds_api_key: str = ""
    oddspapi_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    odds_provider: str = "mock"          # mock | the_odds_api | oddspapi
    min_profit_margin: float = 0.01
    total_stake: float = 1000.0
    scan_interval: int = 60              # segundos entre ciclos del scan loop
    sports: str = "soccer,tennis"
    allowed_bookmakers: str = ""         # comma-separated; vacío = todas las casas
    # --- Gestión de créditos API ---
    api_cache_ttl: int = 21600           # segundos que se guarda la respuesta en caché (default 6h)
    max_fixtures_per_sport: int = 5      # máximo de partidos a consultar por deporte por ciclo

    @property
    def sports_list(self) -> list[str]:
        return [s.strip() for s in self.sports.split(",") if s.strip()]

    @property
    def allowed_bookmakers_set(self) -> frozenset[str]:
        if not self.allowed_bookmakers.strip():
            return frozenset()
        return frozenset(
            b.strip() for b in self.allowed_bookmakers.split(",") if b.strip()
        )


settings = Settings()
