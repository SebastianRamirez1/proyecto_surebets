from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import ArbitrageOpportunity, Market


@runtime_checkable
class OddsProvider(Protocol):
    name: str

    async def fetch_markets(self, sport: str) -> list[Market]: ...


@runtime_checkable
class OpportunityNotifier(Protocol):
    async def notify(self, opportunity: ArbitrageOpportunity) -> None: ...
