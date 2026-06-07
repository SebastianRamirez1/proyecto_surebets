from __future__ import annotations

import asyncio
import logging

from .application.scan_use_case import ScanForArbitrageUseCase
from .config import settings
from .domain.arbitrage import ArbitrageCalculator
from .infrastructure.notifiers.telegram_notifier import TelegramNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def _build_provider() -> object:
    if settings.odds_provider == "mock":
        from .infrastructure.providers.mock_provider import MockOddsProvider
        return MockOddsProvider(arb_probability=0.5)
    else:
        from .infrastructure.providers.the_odds_api import TheOddsApiProvider
        return TheOddsApiProvider(api_key=settings.the_odds_api_key)


async def main() -> None:
    provider = _build_provider()
    calculator = ArbitrageCalculator(
        min_profit_margin=settings.min_profit_margin,
        total_stake=settings.total_stake,
    )
    notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )
    use_case = ScanForArbitrageUseCase(provider, calculator, notifier)  # type: ignore[arg-type]

    logger.info("Sports Arbitrage Detector iniciado (provider=%s)", settings.odds_provider)
    while True:
        try:
            opps = await use_case.execute(settings.sports_list)
            logger.info("Scan completado: %d oportunidades encontradas", len(opps))
            for opp in opps:
                logger.info(
                    "  %s — margen %.2f%%", opp.market.label, opp.profit_margin * 100
                )
        except Exception as exc:
            logger.error("Error en el loop principal: %s", exc)
        await asyncio.sleep(settings.scan_interval)


if __name__ == "__main__":
    asyncio.run(main())
