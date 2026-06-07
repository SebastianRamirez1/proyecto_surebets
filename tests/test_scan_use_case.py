from datetime import UTC, datetime

import pytest

from sports_arb.application.scan_use_case import ScanForArbitrageUseCase
from sports_arb.domain.arbitrage import ArbitrageCalculator
from sports_arb.domain.models import ArbitrageOpportunity, Market, Outcome


def _arb_market() -> Market:
    return Market(
        event_id="evt-arb",
        sport="soccer",
        home_team="A",
        away_team="B",
        commence_time=datetime(2026, 6, 10, tzinfo=UTC),
        market_key="h2h",
        outcomes=(
            Outcome("A", "Bet365", 2.10),
            Outcome("B", "Pinnacle", 2.10),
        ),
    )


class FakeProvider:
    name = "fake"

    def __init__(self, markets: list[Market]) -> None:
        self._markets = markets

    async def fetch_markets(self, sport: str) -> list[Market]:
        return self._markets


class FakeNotifier:
    def __init__(self) -> None:
        self.notified: list[ArbitrageOpportunity] = []

    async def notify(self, opportunity: ArbitrageOpportunity) -> None:
        self.notified.append(opportunity)


@pytest.mark.asyncio
async def test_oportunidad_detectada_llega_al_notifier() -> None:
    provider = FakeProvider([_arb_market()])
    notifier = FakeNotifier()
    calc = ArbitrageCalculator(min_profit_margin=0.01, total_stake=1000)
    use_case = ScanForArbitrageUseCase(provider, calc, notifier)

    await use_case.execute(["soccer"])
    assert len(notifier.notified) == 1


@pytest.mark.asyncio
async def test_duplicado_no_se_notifica_dos_veces() -> None:
    provider = FakeProvider([_arb_market()])
    notifier = FakeNotifier()
    calc = ArbitrageCalculator(min_profit_margin=0.01, total_stake=1000)
    use_case = ScanForArbitrageUseCase(provider, calc, notifier)

    await use_case.execute(["soccer"])
    await use_case.execute(["soccer"])
    assert len(notifier.notified) == 1
