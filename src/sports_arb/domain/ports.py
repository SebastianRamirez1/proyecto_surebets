from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import ArbitrageOpportunity, Market


@runtime_checkable
class OddsProvider(Protocol):
    name: str

    async def fetch_markets(self, sport: str) -> list[Market]: ...

    def invalidate_cache(self) -> None:
        """Limpia la caché interna para forzar un fetch real en el próximo scan.
        Los providers sin caché pueden implementar esto como no-op.
        """

    def available_bookmakers(self) -> list[str]:
        """Lista de casas de apuestas conocidas por este provider.
        Se devuelve ANTES del primer scan para poblar la UI.
        """


@runtime_checkable
class OpportunityNotifier(Protocol):
    async def notify(self, opportunity: ArbitrageOpportunity) -> None: ...
