from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Outcome:
    name: str
    bookmaker: str
    price: float

    def __post_init__(self) -> None:
        if self.price <= 1.0:
            raise ValueError(f"Cuota decimal invalida ({self.price}): debe ser > 1.0")

    @property
    def implied_probability(self) -> float:
        return 1.0 / self.price


@dataclass(frozen=True, slots=True)
class Market:
    event_id: str
    sport: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_key: str
    outcomes: tuple[Outcome, ...]

    @property
    def label(self) -> str:
        return f"{self.home_team} vs {self.away_team}"

    def best_price_per_outcome(self) -> dict[str, Outcome]:
        best: dict[str, Outcome] = {}
        for outcome in self.outcomes:
            current = best.get(outcome.name)
            if current is None or outcome.price > current.price:
                best[outcome.name] = outcome
        return best

    def filter_bookmakers(self, allowed: frozenset[str]) -> Market:
        """Return a copy keeping only outcomes from bookmakers in *allowed*.

        If *allowed* is empty the original market is returned unchanged.
        """
        if not allowed:
            return self
        return Market(
            event_id=self.event_id,
            sport=self.sport,
            home_team=self.home_team,
            away_team=self.away_team,
            commence_time=self.commence_time,
            market_key=self.market_key,
            outcomes=tuple(o for o in self.outcomes if o.bookmaker in allowed),
        )


@dataclass(frozen=True, slots=True)
class ArbitrageBet:
    outcome_name: str
    bookmaker: str
    price: float
    stake: float
    stake_pct: float

    @property
    def guaranteed_return(self) -> float:
        return self.stake * self.price


@dataclass(frozen=True, slots=True)
class ArbitrageOpportunity:
    market: Market
    bets: tuple[ArbitrageBet, ...]
    total_stake: float
    arb_percentage: float
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def profit_margin(self) -> float:
        return (1.0 / self.arb_percentage) - 1.0

    @property
    def profit_amount(self) -> float:
        return self.total_stake * self.profit_margin

    @property
    def is_profitable(self) -> bool:
        return self.arb_percentage < 1.0
