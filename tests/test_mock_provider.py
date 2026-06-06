import pytest
from sports_arb.domain.arbitrage import ArbitrageCalculator
from sports_arb.infrastructure.providers.mock_provider import MockOddsProvider


@pytest.mark.asyncio
async def test_mock_con_arb_probability_1_detecta_oportunidad() -> None:
    provider = MockOddsProvider(arb_probability=1.0, seed=42)
    calc = ArbitrageCalculator(min_profit_margin=0.001, total_stake=1000)
    markets = await provider.fetch_markets("soccer")
    opps = calc.scan(markets)
    assert len(opps) > 0


@pytest.mark.asyncio
async def test_mock_con_arb_probability_0_no_detecta_oportunidad() -> None:
    provider = MockOddsProvider(arb_probability=0.0, seed=42)
    calc = ArbitrageCalculator(min_profit_margin=0.001, total_stake=1000)
    markets = await provider.fetch_markets("soccer")
    opps = calc.scan(markets)
    assert len(opps) == 0
