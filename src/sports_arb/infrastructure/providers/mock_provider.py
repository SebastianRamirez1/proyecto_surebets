from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from ...domain.models import Market, Outcome

_BOOKMAKERS = ("Bet365", "Pinnacle", "William Hill", "Betfair", "1xBet")
_FIXTURES: dict[str, list[tuple[str, str]]] = {
    "soccer": [
        ("Real Madrid", "Barcelona"),
        ("Liverpool", "Manchester City"),
        ("Bayern Munich", "Dortmund"),
        ("Boca Juniors", "River Plate"),
    ],
    "tennis": [
        ("Alcaraz", "Sinner"),
        ("Djokovic", "Medvedev"),
        ("Swiatek", "Sabalenka"),
    ],
}


class MockOddsProvider:
    name = "mock"

    def __init__(self, arb_probability: float = 0.35, seed: int | None = None) -> None:
        self._arb_probability = arb_probability
        self._rng = random.Random(seed)

    async def fetch_markets(self, sport: str) -> list[Market]:
        fixtures = _FIXTURES.get(sport, _FIXTURES["soccer"])
        markets: list[Market] = []
        for i, (home, away) in enumerate(fixtures):
            three_way = sport == "soccer"
            inject_arb = self._rng.random() < self._arb_probability
            outcomes = self._build_outcomes(home, away, three_way, inject_arb)
            markets.append(
                Market(
                    event_id=f"mock-{sport}-{i}",
                    sport=sport,
                    home_team=home,
                    away_team=away,
                    commence_time=datetime.now(UTC)
                    + timedelta(hours=self._rng.randint(1, 48)),
                    market_key="h2h",
                    outcomes=tuple(outcomes),
                )
            )
        return markets

    def _build_outcomes(
        self, home: str, away: str, three_way: bool, inject_arb: bool
    ) -> list[Outcome]:
        names = [home, "Empate", away] if three_way else [home, away]
        fair = [2.7, 3.3, 2.9] if three_way else [1.95, 1.95]
        outcomes: list[Outcome] = []
        for name, fair_price in zip(names, fair, strict=False):
            for book in self._rng.sample(list(_BOOKMAKERS), k=3):
                if inject_arb:
                    price = round(fair_price * self._rng.uniform(1.02, 1.12), 2)
                else:
                    price = round(fair_price * self._rng.uniform(0.90, 0.98), 2)
                outcomes.append(Outcome(name=name, bookmaker=book, price=price))
        return outcomes
