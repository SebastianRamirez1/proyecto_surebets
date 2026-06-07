from __future__ import annotations

import logging
import time

from ..domain.arbitrage import ArbitrageCalculator
from ..domain.models import ArbitrageOpportunity, Market
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
        self._latest_markets: list[Market] = []
        self._last_sports: list[str] = []
        self._last_force: float = 0.0
        self._FORCE_COOLDOWN = 30.0  # segundos mínimos entre force scans

    async def execute(self, sports: list[str]) -> list[ArbitrageOpportunity]:
        all_markets: list[Market] = []
        for sport in sports:
            try:
                markets = await self._provider.fetch_markets(sport)
                all_markets.extend(markets)
            except Exception as exc:
                logger.error("Error al obtener mercados para %s: %s", sport, exc)

        self._latest_markets = all_markets
        self._last_sports = sports
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

    @property
    def latest_markets(self) -> list[Market]:
        return self._latest_markets

    @property
    def known_bookmakers(self) -> list[str]:
        """Sorted list of all bookmakers seen in the latest scan."""
        books: set[str] = set()
        for market in self._latest_markets:
            for outcome in market.outcomes:
                books.add(outcome.bookmaker)
        return sorted(books)

    async def force_scan(self) -> tuple[list[ArbitrageOpportunity], int]:
        """Invalida caché y ejecuta un scan inmediato.

        Returns:
            (opportunities, cooldown_remaining) — cooldown_remaining > 0 significa
            que aún hay que esperar ese número de segundos antes de poder forzar otro scan.
        """
        remaining = self._FORCE_COOLDOWN - (time.monotonic() - self._last_force)
        if remaining > 0:
            return [], int(remaining)
        self._provider.invalidate_cache()
        self._last_force = time.monotonic()
        sports = self._last_sports or ["soccer"]
        opps = await self.execute(sports)
        return opps, 0

    def filter_opportunities(
        self,
        capital: float | None = None,
        allowed_bookmakers: frozenset[str] | None = None,
    ) -> list[ArbitrageOpportunity]:
        """Re-evaluate latest markets with optional capital and/or bookmaker filter."""
        markets = self._latest_markets
        if allowed_bookmakers:
            markets = [m.filter_bookmakers(allowed_bookmakers) for m in markets]
        effective_stake = (
            capital
            if capital is not None and capital > 0
            else self._calculator.total_stake
        )
        calc = ArbitrageCalculator(
            min_profit_margin=self._calculator.min_profit_margin,
            total_stake=effective_stake,
        )
        return calc.scan(markets)
