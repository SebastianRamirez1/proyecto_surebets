"""OddsPapi provider — https://api.oddspapi.io/v4

Estrategia de uso de créditos
──────────────────────────────
OddsPapi free tier: 250 requests/mes.

Cada llamada a fetch_markets() hace:
  1. GET /v4/fixtures?sport=X  →  lista de partidos próximos   (1 req)
  2. GET /v4/odds?fixtureId=X  →  cuotas por partido            (N req)

Para no agotar los créditos se usan dos capas de caché en memoria:
  • _fixtures_cache  — lista de partidos, TTL = api_cache_ttl  (por defecto 6 h)
  • _odds_cache      — cuotas por partido, TTL = api_cache_ttl

Cálculo orientativo (sport=soccer, max_fixtures=5, cache 6 h):
  (1 fixture-req + 5 odds-req) × 4 ciclos/día × 30 días = 720 req/mes  ← se pasa
  Con cache 12 h: (1+5) × 2 × 30 = 360 req/mes                          ← se pasa
  Con cache 24 h: (1+5) × 1 × 30 = 180 req/mes                          ← OK (72 de margen)

Recomendación práctica:
  API_CACHE_TTL=86400  (24 h)  para dev/aprendizaje  → ~180 req/mes
  API_CACHE_TTL=43200  (12 h)  con 1 deporte          → ~180 req/mes
  API_CACHE_TTL=21600  ( 6 h)  con 1 deporte          → ~240 req/mes ← límite
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from ...domain.models import Market, Outcome

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.oddspapi.io/v4"
_H2H_MARKET_KEYS = {"h2h", "1x2", "match_winner", "moneyline"}


# ── Request tracker ────────────────────────────────────────────────────────────

class _RequestTracker:
    """Conteo de requests reales al API (excluye hits de caché)."""

    def __init__(self) -> None:
        self._total = 0
        self._month = 0
        self._month_key = self._current_month()

    @staticmethod
    def _current_month() -> str:
        return datetime.now(UTC).strftime("%Y-%m")

    def record(self) -> None:
        key = self._current_month()
        if key != self._month_key:
            self._month = 0
            self._month_key = key
        self._total += 1
        self._month += 1
        logger.info(
            "OddsPapi: request #%d este mes (total acumulado: %d)",
            self._month,
            self._total,
        )
        if self._month >= 200:
            logger.warning(
                "⚠️  OddsPapi: %d/250 requests usados este mes — quedan ~%d",
                self._month,
                250 - self._month,
            )

    @property
    def this_month(self) -> int:
        return self._month

    @property
    def total(self) -> int:
        return self._total


# ── Provider ───────────────────────────────────────────────────────────────────

class OddsPapiProvider:
    """Proveedor de cuotas usando la API de OddsPapi con caché en memoria."""

    name = "oddspapi"

    def __init__(
        self,
        api_key: str,
        cache_ttl: int = 21600,
        max_fixtures: int = 5,
        timeout: float = 15.0,
    ) -> None:
        if not api_key:
            raise ValueError("Falta ODDSPAPI_KEY en .env")
        self._api_key = api_key
        self._cache_ttl = cache_ttl
        self._max_fixtures = max_fixtures
        self._timeout = timeout
        self._tracker = _RequestTracker()

        # caché: sport -> (lista_fixture_ids, timestamp)
        self._fixtures_cache: dict[str, tuple[list[str], float]] = {}
        # caché: fixture_id -> (Market, timestamp)
        self._odds_cache: dict[str, tuple[Market, float]] = {}

    # ── Public ────────────────────────────────────────────────────────────────

    def invalidate_cache(self) -> None:
        """Limpia toda la caché para que el próximo fetch consulte el API real."""
        self._fixtures_cache.clear()
        self._odds_cache.clear()
        logger.info("OddsPapi: caché invalidada — el próximo scan usará el API real")

    async def fetch_markets(self, sport: str) -> list[Market]:
        fixture_ids = await self._get_fixture_ids(sport)
        markets: list[Market] = []
        for fid in fixture_ids[: self._max_fixtures]:
            market = await self._get_odds(fid, sport)
            if market is not None:
                markets.append(market)
        logger.debug(
            "OddsPapi: %d mercados para '%s' (%d requests este mes)",
            len(markets),
            sport,
            self._tracker.this_month,
        )
        return markets

    @property
    def request_tracker(self) -> _RequestTracker:
        return self._tracker

    # ── Fixtures ──────────────────────────────────────────────────────────────

    async def _get_fixture_ids(self, sport: str) -> list[str]:
        cached = self._fixtures_cache.get(sport)
        if cached and (time.monotonic() - cached[1]) < self._cache_ttl:
            logger.debug("OddsPapi: fixtures para '%s' servidos desde caché", sport)
            return cached[0]

        self._tracker.record()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        params = {
            "apiKey": self._api_key,
            "sport": sport,
            "from": today,
            "status": "upcoming",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{_BASE_URL}/fixtures", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "OddsPapi fixtures error %s: %s",
                exc.response.status_code,
                exc.response.text[:300],
            )
            return []
        except httpx.HTTPError as exc:
            logger.error("OddsPapi fixtures error de red: %s", exc)
            return []

        ids = self._parse_fixture_ids(data)
        self._fixtures_cache[sport] = (ids, time.monotonic())
        logger.info("OddsPapi: %d fixtures encontrados para '%s'", len(ids), sport)
        return ids

    @staticmethod
    def _parse_fixture_ids(data: object) -> list[str]:
        """Extrae IDs de la respuesta de fixtures (varios formatos posibles)."""
        ids: list[str] = []
        items: list[object] = []

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # { "data": [...] }  o  { "fixtures": [...] }
            for key in ("data", "fixtures", "results"):
                val = data.get(key)
                if isinstance(val, list):
                    items = val
                    break
            if not items:
                # la respuesta ya es el dict de un fixture único
                items = [data]

        for item in items:
            if not isinstance(item, dict):
                continue
            fid = (
                item.get("fixtureId")
                or item.get("fixture_id")
                or item.get("id")
            )
            if fid is not None:
                ids.append(str(fid))
        return ids

    # ── Odds ──────────────────────────────────────────────────────────────────

    async def _get_odds(self, fixture_id: str, sport: str) -> Market | None:
        cached = self._odds_cache.get(fixture_id)
        if cached and (time.monotonic() - cached[1]) < self._cache_ttl:
            logger.debug("OddsPapi: odds para fixture %s desde caché", fixture_id)
            return cached[0]

        self._tracker.record()
        params = {
            "apiKey": self._api_key,
            "fixtureId": fixture_id,
            "oddsFormat": "decimal",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{_BASE_URL}/odds", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "OddsPapi odds error %s para fixture %s: %s",
                exc.response.status_code,
                fixture_id,
                exc.response.text[:300],
            )
            return None
        except httpx.HTTPError as exc:
            logger.error("OddsPapi odds error de red (fixture %s): %s", fixture_id, exc)
            return None

        market = self._parse_odds(data, fixture_id, sport)
        if market is not None:
            self._odds_cache[fixture_id] = (market, time.monotonic())
        return market

    def _parse_odds(
        self, data: object, fixture_id: str, sport: str
    ) -> Market | None:
        """Convierte la respuesta JSON de odds en un Market del dominio."""
        if not isinstance(data, dict):
            return None

        # Navegar al objeto raíz del fixture (puede estar dentro de "data")
        root: dict[str, object] = data
        nested = data.get("data")
        if isinstance(nested, dict):
            root = nested

        home = str(root.get("participant1Name") or root.get("home_team") or "?")
        away = str(root.get("participant2Name") or root.get("away_team") or "?")
        sport_name = str(root.get("sportName") or root.get("sport") or sport)
        start_raw = root.get("startTime") or root.get("commence_time") or ""
        try:
            commence = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        except ValueError:
            commence = datetime.now(UTC)

        outcomes: list[Outcome] = []
        bookmaker_list = root.get("bookmakerOdds") or root.get("bookmakers") or []
        if not isinstance(bookmaker_list, list):
            return None

        for bk in bookmaker_list:
            if not isinstance(bk, dict):
                continue
            book_name = str(
                bk.get("bookmakerName") or bk.get("title") or bk.get("key") or "?"
            )
            markets_raw = bk.get("markets") or []
            if not isinstance(markets_raw, list):
                continue
            for mkt in markets_raw:
                if not isinstance(mkt, dict):
                    continue
                mkt_key = str(mkt.get("marketType") or mkt.get("key") or "").lower()
                if mkt_key not in _H2H_MARKET_KEYS and mkt_key != "":
                    continue
                for oc in mkt.get("outcomes") or []:
                    if not isinstance(oc, dict):
                        continue
                    name = oc.get("name") or oc.get("participant")
                    price = oc.get("price") or oc.get("odds")
                    if not isinstance(price, (int, float)) or price <= 1.0 or not name:
                        continue
                    try:
                        outcomes.append(
                            Outcome(
                                name=str(name),
                                bookmaker=book_name,
                                price=float(price),
                            )
                        )
                    except ValueError:
                        continue

        if not outcomes:
            logger.debug("OddsPapi: sin outcomes válidos para fixture %s", fixture_id)
            return None

        return Market(
            event_id=fixture_id,
            sport=sport_name,
            home_team=home,
            away_team=away,
            commence_time=commence,
            market_key="h2h",
            outcomes=tuple(outcomes),
        )
