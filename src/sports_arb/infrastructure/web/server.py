"""Entry point for uvicorn: wires the use case into the FastAPI app and runs the scan loop."""
from __future__ import annotations

import asyncio
import logging

from ...application.scan_use_case import ScanForArbitrageUseCase
from ...config import settings
from ...domain.arbitrage import ArbitrageCalculator
from ...infrastructure.notifiers.telegram_notifier import TelegramNotifier
from .app import create_app

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")


def _build_provider() -> object:
    if settings.odds_provider == "oddspapi":
        from ..providers.oddspapi_provider import OddsPapiProvider
        provider = OddsPapiProvider(
            api_key=settings.oddspapi_key,
            cache_ttl=settings.api_cache_ttl,
            max_fixtures=settings.max_fixtures_per_sport,
        )
        logger.info(
            "OddsPapi activo — caché TTL %ds, máx %d fixtures/deporte",
            settings.api_cache_ttl,
            settings.max_fixtures_per_sport,
        )
        return provider
    if settings.odds_provider == "scraper":
        from ..providers.scraper_provider import ScraperProvider
        provider_s = ScraperProvider(
            cache_ttl=settings.api_cache_ttl,
            max_matches=settings.max_fixtures_per_sport,
        )
        logger.info(
            "Scraper activo — caché TTL %ds, máx %d partidos/deporte",
            settings.api_cache_ttl,
            settings.max_fixtures_per_sport,
        )
        return provider_s
    if settings.odds_provider == "the_odds_api":
        from ..providers.the_odds_api import TheOddsApiProvider
        return TheOddsApiProvider(api_key=settings.the_odds_api_key)
    from ..providers.mock_provider import MockOddsProvider
    return MockOddsProvider(arb_probability=0.5)


_provider = _build_provider()
_calculator = ArbitrageCalculator(
    min_profit_margin=settings.min_profit_margin,
    total_stake=settings.total_stake,
)
_notifier = TelegramNotifier(
    bot_token=settings.telegram_bot_token,
    chat_id=settings.telegram_chat_id,
)
_use_case = ScanForArbitrageUseCase(_provider, _calculator, _notifier)  # type: ignore[arg-type]

app = create_app(_use_case)


@app.on_event("startup")
async def start_scan_loop() -> None:
    asyncio.create_task(_scan_loop())


async def _scan_loop() -> None:
    while True:
        try:
            opps = await _use_case.execute(settings.sports_list)
            logger.info("Scan: %d oportunidades", len(opps))
            await app.state.broadcast_refresh()
        except Exception as exc:
            logger.error("Error en scan loop: %s", exc)
        await asyncio.sleep(settings.scan_interval)
