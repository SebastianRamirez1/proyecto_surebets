from datetime import datetime, timezone
import pytest
from sports_arb.domain.arbitrage import ArbitrageCalculator
from sports_arb.domain.models import Market, Outcome


def _market(outcomes: list[Outcome], market_key: str = "h2h") -> Market:
    return Market(
        event_id="evt-1",
        sport="soccer",
        home_team="Equipo A",
        away_team="Equipo B",
        commence_time=datetime(2026, 6, 10, tzinfo=timezone.utc),
        market_key=market_key,
        outcomes=tuple(outcomes),
    )


def test_detecta_arbitraje_claro_dos_vias() -> None:
    market = _market([
        Outcome("A", "Bet365", 2.10), Outcome("B", "Pinnacle", 2.10),
        Outcome("A", "Pinnacle", 1.90), Outcome("B", "Bet365", 1.85),
    ])
    calc = ArbitrageCalculator(min_profit_margin=0.01, total_stake=1000)
    opp = calc.find_opportunity(market)
    assert opp is not None and opp.is_profitable
    assert opp.arb_percentage == pytest.approx(0.952, abs=1e-3)
    assert opp.profit_margin == pytest.approx(0.05, abs=1e-3)
    assert all(bet.price == 2.10 for bet in opp.bets)


def test_no_hay_arbitraje_cuando_la_casa_tiene_margen() -> None:
    market = _market([Outcome("A", "Bet365", 1.90), Outcome("B", "Bet365", 1.90)])
    assert ArbitrageCalculator().find_opportunity(market) is None


def test_filtra_margenes_por_debajo_del_umbral() -> None:
    market = _market([Outcome("A", "Bet365", 2.01), Outcome("B", "Pinnacle", 2.01)])
    assert ArbitrageCalculator(min_profit_margin=0.01).find_opportunity(market) is None


def test_reparto_de_stake_garantiza_mismo_retorno() -> None:
    market = _market([Outcome("A", "Bet365", 2.20), Outcome("B", "Pinnacle", 2.05)])
    opp = ArbitrageCalculator(min_profit_margin=0.005, total_stake=1000).find_opportunity(market)
    assert opp is not None
    retornos = [b.guaranteed_return for b in opp.bets]
    assert max(retornos) == pytest.approx(min(retornos), abs=0.5)
    assert min(retornos) > opp.total_stake


def test_suma_de_stakes_no_excede_capital() -> None:
    market = _market([Outcome("A", "Bet365", 2.30), Outcome("B", "Pinnacle", 2.10)])
    opp = ArbitrageCalculator(min_profit_margin=0.005, total_stake=1000).find_opportunity(market)
    assert opp is not None
    assert sum(b.stake for b in opp.bets) == pytest.approx(1000, abs=1.0)


def test_arbitraje_tres_vias_futbol() -> None:
    market = _market([
        Outcome("Local", "Bet365", 3.10),
        Outcome("Empate", "Pinnacle", 3.70),
        Outcome("Visitante", "William Hill", 3.00),
    ])
    opp = ArbitrageCalculator(min_profit_margin=0.01, total_stake=1000).find_opportunity(market)
    assert opp is not None and len(opp.bets) == 3 and opp.profit_margin > 0.05


def test_mercado_con_un_solo_resultado_no_arbitra() -> None:
    assert ArbitrageCalculator().find_opportunity(_market([Outcome("A", "Bet365", 2.50)])) is None


def test_cuota_invalida_lanza_error() -> None:
    with pytest.raises(ValueError):
        Outcome("A", "Bet365", 1.0)


def test_scan_ordena_por_margen_descendente() -> None:
    m1 = _market([Outcome("A", "X", 2.05), Outcome("B", "Y", 2.05)])
    m2 = _market([Outcome("C", "X", 2.30), Outcome("D", "Y", 2.30)])
    opps = ArbitrageCalculator(min_profit_margin=0.01, total_stake=1000).scan([m1, m2])
    assert len(opps) == 2 and opps[0].profit_margin > opps[1].profit_margin
