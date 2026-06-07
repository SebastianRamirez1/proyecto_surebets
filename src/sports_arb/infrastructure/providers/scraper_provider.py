"""Scraper de cuotas sobre OddsPortal (https://www.oddsportal.com)

Cómo funciona
─────────────
OddsPortal carga los datos de cuotas en dos fases:
  1. Página HTML del deporte  →  contiene IDs de partidos embebidos en el JS
  2. Endpoint XHR interno     →  devuelve JSON con cuotas por partido

No requiere API key ni registro.

Buenas prácticas implementadas
───────────────────────────────
- User-Agent realista + headers de navegador
- Delay configurable entre requests (default 2 s)
- Caché en memoria con TTL configurable (default 30 min)
- Máximo de partidos configurable para no sobrecargar
- Logging detallado para poder depurar cuando el sitio cambia

Notas de mantenimiento
──────────────────────
Los selectores CSS y las rutas de los endpoints pueden cambiar cuando
OddsPortal actualiza su front-end. Si algo deja de funcionar abrí
DevTools → Network → XHR/Fetch y buscá las requests que cargan cuotas.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from ...domain.models import Market, Outcome

logger = logging.getLogger(__name__)

_BASE = "https://www.oddsportal.com"

# Mapeo de nombre de deporte del proyecto → slug en OddsPortal
_SPORT_SLUG: dict[str, str] = {
    "soccer":     "soccer",
    "football":   "soccer",
    "tennis":     "tennis",
    "basketball": "basketball",
    "baseball":   "baseball",
    "hockey":     "hockey",
    "volleyball": "volleyball",
    "handball":   "handball",
}

# Headers que simulan un navegador real
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_AJAX_HEADERS = {
    **_HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": _BASE,
}


class ScraperProvider:
    """Proveedor de cuotas via scraping de OddsPortal."""

    name = "scraper"

    def __init__(
        self,
        request_delay: float = 2.0,
        cache_ttl: int = 1800,
        max_matches: int = 5,
        timeout: float = 20.0,
    ) -> None:
        self._delay = request_delay
        self._cache_ttl = cache_ttl
        self._max_matches = max_matches
        self._timeout = timeout

        # caché: sport -> (markets, timestamp)
        self._cache: dict[str, tuple[list[Market], float]] = {}

    # ── Protocol ─────────────────────────────────────────────────────────────

    def invalidate_cache(self) -> None:
        self._cache.clear()
        logger.info("Scraper: caché limpiada")

    def available_bookmakers(self) -> list[str]:
        # OddsPortal agrega ~60 casas; listamos las más comunes
        return [
            "1xBet", "888sport", "Bet365", "Betfair",
            "Betsson", "Betway", "Bwin", "Coral",
            "Ladbrokes", "Pinnacle", "Unibet", "William Hill",
        ]

    async def fetch_markets(self, sport: str) -> list[Market]:
        cached = self._cache.get(sport)
        if cached and (time.monotonic() - cached[1]) < self._cache_ttl:
            logger.debug("Scraper: '%s' desde caché", sport)
            return cached[0]

        markets = await self._scrape(sport)
        self._cache[sport] = (markets, time.monotonic())
        logger.info("Scraper: %d mercados para '%s'", len(markets), sport)
        return markets

    # ── Scraping ──────────────────────────────────────────────────────────────

    async def _scrape(self, sport: str) -> list[Market]:
        slug = _SPORT_SLUG.get(sport.lower(), sport.lower())
        url = f"{_BASE}/{slug}/"

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            # 1. Página principal — obtener cookies de sesión + IDs de partidos
            logger.info("Scraper: GET %s", url)
            try:
                resp = await client.get(url, headers=_HEADERS)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("Scraper: HTTP %s en %s", exc.response.status_code, url)
                return []
            except httpx.HTTPError as exc:
                logger.error("Scraper: error de red en %s — %s", url, exc)
                return []

            html = resp.text
            cookies = dict(resp.cookies)
            match_ids = self._extract_match_ids(html)

            if not match_ids:
                logger.warning(
                    "Scraper: no se encontraron IDs de partidos en %s — "
                    "OddsPortal puede haber cambiado su HTML. "
                    "Abrí DevTools → Network → XHR y buscá el endpoint de partidos.",
                    url,
                )
                return []

            logger.info("Scraper: %d partidos encontrados", len(match_ids))

            # 2. Cuotas por partido
            markets: list[Market] = []
            for mid in match_ids[: self._max_matches]:
                await asyncio.sleep(self._delay)
                market = await self._fetch_match_odds(client, mid, sport, cookies)
                if market is not None:
                    markets.append(market)

        return markets

    def _extract_match_ids(self, html: str) -> list[str]:
        """Extrae IDs de partidos del HTML de OddsPortal.

        OddsPortal embebe los datos de partidos en el JavaScript de la página
        como objetos JSON dentro de <script> tags. Buscamos el patrón
        que contiene los IDs únicos de cada partido.
        """
        ids: list[str] = []

        # Patrón 1: IDs en atributos data-* de elementos del DOM
        soup = BeautifulSoup(html, "lxml")
        for el in soup.select("[data-id]"):
            mid = el.get("data-id")
            if mid and isinstance(mid, str) and len(mid) > 6 and mid not in ids:
                ids.append(mid)

        # Patrón 2: IDs en el JS embebido (formato "id":"xABCDEF")
        if not ids:
            for match in re.finditer(r'"id"\s*:\s*"([a-zA-Z0-9]{8,})"', html):
                mid = match.group(1)
                if mid not in ids:
                    ids.append(mid)

        # Patrón 3: links con /match/ en el href
        if not ids:
            for a in soup.select("a[href*='/match/']"):
                href = str(a.get("href", ""))
                # /match/soccer/spain/laliga/real-madrid-barcelona/xABCDEF/
                parts = [p for p in href.split("/") if p]
                if parts:
                    mid = parts[-1]
                    if re.match(r"^[a-zA-Z0-9]{6,}$", mid) and mid not in ids:
                        ids.append(mid)

        logger.debug("Scraper: IDs extraídos: %s", ids[:10])
        return ids

    async def _fetch_match_odds(
        self,
        client: httpx.AsyncClient,
        match_id: str,
        sport: str,
        cookies: dict[str, str],
    ) -> Market | None:
        """Llama al endpoint interno de OddsPortal para obtener cuotas de un partido."""
        # OddsPortal usa esta URL para cargar cuotas vía XHR
        ajax_url = f"{_BASE}/feed/match-event/?id={match_id}&isHistory=false"

        logger.debug("Scraper: GET odds %s", ajax_url)
        try:
            resp = await client.get(
                ajax_url,
                headers={**_AJAX_HEADERS, "Referer": f"{_BASE}/{sport}/"},
                cookies=cookies,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Scraper: HTTP %s para match %s", exc.response.status_code, match_id)
            return None
        except httpx.HTTPError as exc:
            logger.warning("Scraper: error de red para match %s — %s", match_id, exc)
            return None
        except Exception as exc:
            logger.warning("Scraper: respuesta no es JSON para match %s — %s", match_id, exc)
            return None

        return self._parse_match(data, match_id, sport)

    def _parse_match(
        self, data: object, match_id: str, sport: str
    ) -> Market | None:
        """Convierte la respuesta JSON de OddsPortal en un Market del dominio."""
        if not isinstance(data, dict):
            return None

        # Navegar al nodo del evento (puede estar bajo "d" o "data")
        event: dict[str, object] = {}
        for key in ("d", "data", "event"):
            val = data.get(key)
            if isinstance(val, dict):
                event = val
                break
        if not event:
            event = data

        home = str(event.get("home") or event.get("home_name") or event.get("participant1") or "?")
        away = str(event.get("away") or event.get("away_name") or event.get("participant2") or "?")
        sport_name = str(event.get("sport") or sport)

        start_ts = event.get("start_time") or event.get("startTime") or event.get("time")
        try:
            commence = (
                datetime.fromtimestamp(float(str(start_ts)), tz=UTC)
                if start_ts is not None
                else datetime.now(UTC)
            )
        except (ValueError, TypeError, OSError):
            commence = datetime.now(UTC)

        outcomes: list[Outcome] = []
        # Las cuotas están bajo "odds" o "bookmakers"
        odds_data = event.get("odds") or event.get("bookmakers") or data.get("odds") or {}

        if isinstance(odds_data, dict):
            # Formato: {"Bet365": {"1": 2.10, "X": 3.30, "2": 4.00}, ...}
            for book_name, markets in odds_data.items():
                if not isinstance(markets, dict):
                    continue
                for outcome_name, price in markets.items():
                    try:
                        p = float(str(price))
                        if p <= 1.0:
                            continue
                        # Normalizar "1"/"X"/"2" a nombres legibles
                        label = _normalize_outcome(outcome_name, home, away)
                        outcomes.append(
                            Outcome(name=label, bookmaker=str(book_name), price=p)
                        )
                    except (ValueError, TypeError):
                        continue

        elif isinstance(odds_data, list):
            # Formato alternativo: [{"bookmaker": "Bet365", "outcome": "1", "odds": 2.10}, ...]
            for row in odds_data:
                if not isinstance(row, dict):
                    continue
                book = str(row.get("bookmaker") or row.get("name") or "?")
                outcome_name = str(row.get("outcome") or row.get("result") or "?")
                price_raw = row.get("odds") or row.get("price")
                try:
                    p = float(str(price_raw))
                    if p <= 1.0:
                        continue
                    label = _normalize_outcome(outcome_name, home, away)
                    outcomes.append(Outcome(name=label, bookmaker=book, price=p))
                except (ValueError, TypeError):
                    continue

        if not outcomes:
            logger.debug(
                "Scraper: sin outcomes para match %s — "
                "keys disponibles: %s",
                match_id,
                list(event.keys())[:15],
            )
            return None

        return Market(
            event_id=f"scraper-{match_id}",
            sport=sport_name,
            home_team=home,
            away_team=away,
            commence_time=commence,
            market_key="h2h",
            outcomes=tuple(outcomes),
        )


def _normalize_outcome(raw: str, home: str, away: str) -> str:
    """Convierte "1"/"X"/"2" al nombre real del equipo o resultado."""
    mapping: dict[str, str] = {
        "1": home,
        "2": away,
        "X": "Empate",
        "x": "Empate",
        "draw": "Empate",
        "home": home,
        "away": away,
    }
    return mapping.get(raw.strip(), raw.strip())
