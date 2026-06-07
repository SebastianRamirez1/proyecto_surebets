from __future__ import annotations

import logging

from ..domain.arbitrage import ArbitrageCalculator
from ..domain.models import ArbitrageOpportunity
from ..domain.ports import OddsProvider, OpportunityNotifier

logger = logging.getLogger(__name__)


class ScanForArbitrageUseCase:
    def __init__(
        self,
        provider: OddsProvider,
        calculator: ArbitrageCalculator,
        notifier: OpportunityNotifier,
    ) -> None:
        self._provider = provider
        self._calculator = calculator
        self._notifier = notifier
        self._seen: set[str] = set()
        self._latest: list[ArbitrageOpportunity] = []

    async def execute(self, sports: list[str]) -> list[ArbitrageOpportunity]:
        all_markets = []
        for sport in sports:
            try:
                markets = await self._provider.fetch_markets(sport)
                all_markets.extend(markets)
            except Exception as exc:
                logger.error("Error al obtener mercados para %s: %s", sport, exc)

        opportunities = self._calculator.scan(all_markets)
        self._latest = opportunities

        for opp in opportunities:
            key = f"{opp.market.event_id}:{opp.arb_percentage:.6f}"
            if key not in self._seen:
                self._seen.add(key)
                try:
                    await self._notifier.notify(opp)
                except Exception as exc:
                    logger.error("Error al notificar oportunidad: %s", exc)

        return opportunities

    @property
    def latest_opportunities(self) -> list[ArbitrageOpportunity]:
        return self._latest
