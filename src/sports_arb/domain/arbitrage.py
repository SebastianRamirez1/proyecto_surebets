from __future__ import annotations
from .models import ArbitrageBet, ArbitrageOpportunity, Market


class ArbitrageCalculator:
    def __init__(self, min_profit_margin: float = 0.01, total_stake: float = 1000.0) -> None:
        if not 0.0 <= min_profit_margin < 1.0:
            raise ValueError("min_profit_margin debe estar en [0, 1)")
        if total_stake <= 0:
            raise ValueError("total_stake debe ser positivo")
        self._min_profit_margin = min_profit_margin
        self._total_stake = total_stake

    def find_opportunity(self, market: Market) -> ArbitrageOpportunity | None:
        best = market.best_price_per_outcome()
        if len(best) < 2:
            return None
        arb_pct = sum(o.implied_probability for o in best.values())
        if arb_pct >= 1.0:
            return None
        profit_margin = (1.0 / arb_pct) - 1.0
        if profit_margin < self._min_profit_margin:
            return None
        bets = self._distribute_stake(best, arb_pct)
        return ArbitrageOpportunity(
            market=market,
            bets=bets,
            total_stake=self._total_stake,
            arb_percentage=arb_pct,
        )

    def _distribute_stake(
        self, best_outcomes: dict[str, object], arb_pct: float
    ) -> tuple[ArbitrageBet, ...]:
        from .models import Outcome
        bets: list[ArbitrageBet] = []
        for name, outcome in best_outcomes.items():
            assert isinstance(outcome, Outcome)
            fraction = outcome.implied_probability / arb_pct
            stake = round(self._total_stake * fraction, 2)
            bets.append(
                ArbitrageBet(
                    outcome_name=name,
                    bookmaker=outcome.bookmaker,
                    price=outcome.price,
                    stake=stake,
                    stake_pct=round(fraction * 100, 2),
                )
            )
        return tuple(bets)

    def scan(self, markets: list[Market]) -> list[ArbitrageOpportunity]:
        found = [
            opp
            for market in markets
            if (opp := self.find_opportunity(market)) is not None
        ]
        found.sort(key=lambda o: o.profit_margin, reverse=True)
        return found
