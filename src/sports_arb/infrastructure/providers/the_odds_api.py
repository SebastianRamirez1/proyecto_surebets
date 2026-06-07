from __future__ import annotations

from datetime import datetime

import httpx

from ...domain.models import Market, Outcome

_BASE_URL = "https://api.the-odds-api.com/v4"


class TheOddsApiError(RuntimeError):
    pass


class TheOddsApiProvider:
    name = "the_odds_api"

    def __init__(
        self,
        api_key: str,
        regions: str = "eu,uk",
        market_key: str = "h2h",
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("Falta la API key de The Odds API")
        self._api_key = api_key
        self._regions = regions
        self._market_key = market_key
        self._timeout = timeout

    def invalidate_cache(self) -> None:
        pass  # this provider makes a fresh request every call

    async def fetch_markets(self, sport: str) -> list[Market]:
        params = {
            "apiKey": self._api_key,
            "regions": self._regions,
            "markets": self._market_key,
            "oddsFormat": "decimal",
        }
        url = f"{_BASE_URL}/sports/{sport}/odds"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                payload: list[dict[str, object]] = resp.json()
        except httpx.HTTPStatusError as exc:
            raise TheOddsApiError(
                f"The Odds API respondio {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise TheOddsApiError(f"Error de red consultando odds: {exc}") from exc
        return [self._to_market(event, sport) for event in payload]

    def _to_market(self, event: dict[str, object], sport: str) -> Market:
        outcomes: list[Outcome] = []
        for book in event.get("bookmakers", []):  # type: ignore[attr-defined]
            assert isinstance(book, dict)
            book_title = str(book.get("title", book.get("key", "desconocido")))
            for market in book.get("markets", []):
                assert isinstance(market, dict)
                if market.get("key") != self._market_key:
                    continue
                for oc in market.get("outcomes", []):
                    assert isinstance(oc, dict)
                    price = oc.get("price")
                    name = oc.get("name")
                    if not isinstance(price, (int, float)) or price <= 1.0 or not name:
                        continue
                    outcomes.append(
                        Outcome(name=str(name), bookmaker=book_title, price=float(price))
                    )
        return Market(
            event_id=str(event.get("id", "")),
            sport=sport,
            home_team=str(event.get("home_team", "?")),
            away_team=str(event.get("away_team", "?")),
            commence_time=self._parse_time(event.get("commence_time")),  # type: ignore[arg-type]
            market_key=self._market_key,
            outcomes=tuple(outcomes),
        )

    @staticmethod
    def _parse_time(raw: str | None) -> datetime:
        if not raw:
            return datetime.now().astimezone()
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
