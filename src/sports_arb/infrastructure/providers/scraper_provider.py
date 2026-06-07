"""Scraper de cuotas usando Flashscore (https://www.flashscore.com).

Arquitectura
────────────
Fase 1 — Lista de partidos (httpx, sin browser):
  GET https://global.flashscore.ninja/2/x/feed/f_1_0_{tz}_en_1
  Formato propietario de Flashscore: campos KEY÷VALUE¬ separados por chr(247)/chr(172).
  Extraemos: AA=match_id, CX=home, AF=away, AD=timestamp_unix.

Fase 2 — Cuotas (Playwright, headless Chromium):
  Para cada partido navegamos a https://www.flashscore.com/match/{id}/
  Hacemos click en el tab "ODDS" y extraemos las filas de la tabla de
  comparación de cuotas del DOM renderizado.

Instalación (una sola vez)
──────────────────────────
    pip install playwright
    playwright install chromium

Notas de mantenimiento
──────────────────────
Flashscore actualiza su front-end frecuentemente. Si algo deja de funcionar:
- Arrancá con LOG_LEVEL=DEBUG para ver qué feeds/feeds se capturan
- Abrí devtools en https://www.flashscore.com y buscá los feeds ninja
- Los separadores de campo son chr(247)=÷ y chr(172)=¬
"""
from __future__ import annotations

import asyncio
import logging
import socket
import time
from datetime import UTC, datetime

import httpx

from ...domain.models import Market, Outcome

logger = logging.getLogger(__name__)

# ── Constantes del protocolo Flashscore ───────────────────────────────────────
_FIELD_SEP = chr(247)   # ÷  separa nombre de campo de su valor
_FIELD_END = chr(172)   # ¬  termina un campo
_RECORD_SEP = "~"       # separa registros de partido dentro de la respuesta

_NINJA_BASE = "https://global.flashscore.ninja/2/x/feed"
_FS_BASE = "https://www.flashscore.com"

# Headers que Flashscore exige en las peticiones al feed
_FEED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.flashscore.com/",
    "Origin": "https://www.flashscore.com",
    "X-Fsign": "SW9D1eZo",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Mapeo de deporte del proyecto → parámetro numérico en el feed de Flashscore
_SPORT_ID: dict[str, str] = {
    "soccer": "1",
    "football": "1",
    "tennis": "2",
    "basketball": "3",
    "baseball": "16",
    "hockey": "4",
    "volleyball": "23",
    "handball": "6",
}


class ScraperProvider:
    """Proveedor de cuotas via scraping de Flashscore."""

    name = "scraper"

    def __init__(
        self,
        request_delay: float = 2.5,
        cache_ttl: int = 1800,
        max_matches: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self._delay = request_delay
        self._cache_ttl = cache_ttl
        self._max_matches = max_matches
        self._timeout_ms = int(timeout * 1000)

        # sport -> (markets, monotonic_ts)
        self._cache: dict[str, tuple[list[Market], float]] = {}
        # IP resueltas en el inicio (evita fallos DNS de Chromium)
        self._fs_ip: str | None = None
        self._ninja_ip: str | None = None

    # ── Protocol ─────────────────────────────────────────────────────────────

    def invalidate_cache(self) -> None:
        self._cache.clear()
        logger.info("Scraper: caché limpiada")

    def available_bookmakers(self) -> list[str]:
        return sorted([
            "Bet365", "Betano", "Betway", "Bwin",
            "1xBet", "Pinnacle", "Unibet", "William Hill",
            "888sport", "Betfair", "Betsson", "Ladbrokes",
        ])

    async def fetch_markets(self, sport: str) -> list[Market]:
        cached = self._cache.get(sport)
        if cached and (time.monotonic() - cached[1]) < self._cache_ttl:
            logger.debug("Scraper: '%s' desde caché", sport)
            return cached[0]

        markets = await self._scrape(sport)
        self._cache[sport] = (markets, time.monotonic())
        logger.info("Scraper: %d mercados para '%s'", len(markets), sport)
        return markets

    # ── Fase 1: lista de partidos vía httpx ───────────────────────────────────

    async def _fetch_match_list(self, sport: str) -> list[dict[str, str]]:
        """Obtiene la lista de próximos partidos desde el feed de Flashscore."""
        sport_id = _SPORT_ID.get(sport.lower(), "1")
        # El -5 es el offset de timezone en horas (muestra partidos de las próximas horas)
        url = f"{_NINJA_BASE}/f_{sport_id}_0_-5_en_1"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=_FEED_HEADERS)
                resp.raise_for_status()
                raw = resp.text
        except httpx.HTTPError as exc:
            logger.error("Scraper: error obteniendo feed — %s", exc)
            return []

        return _parse_flashscore_feed(raw)

    # ── Fase 2: cuotas vía Playwright ─────────────────────────────────────────

    async def _scrape(self, sport: str) -> list[Market]:
        # Resolver IPs con el sistema DNS (más fiable que el DNS interno de Chromium)
        self._resolve_dns()

        matches = await self._fetch_match_list(sport)
        if not matches:
            logger.warning("Scraper: no se encontraron partidos para '%s'", sport)
            return []

        logger.info("Scraper: %d partidos en el feed, procesando primeros %d",
                    len(matches), self._max_matches)

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Playwright no está instalado.\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )
            return []

        markets: list[Market] = []

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=self._chromium_args(),
                )
                ctx = await browser.new_context(
                    user_agent=_FEED_HEADERS["User-Agent"],
                    locale="en-US",
                    viewport={"width": 1280, "height": 900},
                )

                for match in matches[: self._max_matches]:
                    await asyncio.sleep(self._delay)
                    market = await self._scrape_match_odds(ctx, match, sport)
                    if market:
                        markets.append(market)

                await browser.close()

        except Exception as exc:
            logger.error("Scraper: error general — %s", exc, exc_info=True)

        return markets

    def _resolve_dns(self) -> None:
        """Resuelve IPs una sola vez; las usa en `--host-resolver-rules`."""
        if self._fs_ip and self._ninja_ip:
            return
        try:
            self._fs_ip = socket.gethostbyname("www.flashscore.com")
            self._ninja_ip = socket.gethostbyname("global.flashscore.ninja")
            logger.debug("Scraper: DNS  flashscore=%s  ninja=%s", self._fs_ip, self._ninja_ip)
        except OSError as exc:
            logger.warning("Scraper: no se pudo resolver DNS — %s", exc)
            self._fs_ip = None
            self._ninja_ip = None

    def _chromium_args(self) -> list[str]:
        args = ["--no-sandbox", "--disable-dev-shm-usage"]
        if self._fs_ip and self._ninja_ip:
            rules = (
                f"MAP www.flashscore.com {self._fs_ip},"
                f"MAP global.flashscore.ninja {self._ninja_ip}"
            )
            args.append(f"--host-resolver-rules={rules}")
        return args

    async def _scrape_match_odds(
        self, ctx: object, match: dict[str, str], sport: str
    ) -> Market | None:
        """Navega a la página del partido, hace click en ODDS y extrae cuotas."""
        from playwright.async_api import BrowserContext

        match_id = match["id"]
        home = match.get("home", "?")
        away = match.get("away", "?")
        ts = match.get("ts", "")

        try:
            commence = (
                datetime.fromtimestamp(float(ts), tz=UTC)
                if ts else datetime.now(UTC)
            )
        except (ValueError, OSError):
            commence = datetime.now(UTC)

        url = f"{_FS_BASE}/match/{match_id}/"
        logger.debug("Scraper: %s vs %s — %s", home, away, url)

        assert isinstance(ctx, BrowserContext)
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded",
                            timeout=self._timeout_ms)
            await asyncio.sleep(2)

            # Hacer click en el tab "ODDS"
            tabs = await page.query_selector_all("a, button")
            clicked = False
            for tab in tabs:
                try:
                    txt = (await tab.inner_text()).strip().upper()
                    if txt in ("ODDS", "ODDS COMPARISON"):
                        await tab.click()
                        await asyncio.sleep(3)
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                logger.debug("Scraper: tab ODDS no encontrado para %s", match_id)

            # Extraer pares (bookmaker, odds) de la tabla
            import json as _json
            raw_json: str = await page.evaluate(_JS_EXTRACT_ODDS_ROWS)
            book_odds: list[dict[str, object]] = _json.loads(raw_json)
            outcomes = _book_odds_to_outcomes(book_odds, home, away)

            if not outcomes:
                logger.debug(
                    "Scraper: sin outcomes para %s vs %s (%d bookmakers en DOM)",
                    home, away, len(book_odds),
                )
                return None

            return Market(
                event_id=f"fs-{match_id}",
                sport=sport,
                home_team=home,
                away_team=away,
                commence_time=commence,
                market_key="h2h",
                outcomes=tuple(outcomes),
            )

        except Exception as exc:
            logger.warning("Scraper: error en %s vs %s — %s", home, away, exc)
            return None
        finally:
            await page.close()


# ── JS embebido — extrae pares (bookmaker, odds[]) de la tabla de Flashscore ──
# Usa concatenación de strings para evitar problemas de escape Python ↔ JS.
# Estructura del DOM de Flashscore (2025):
#   .oddsTab__tableWrapper
#     img[src*="bookmakers"][alt="Bookmaker Name"]  ← nombres por orden
#     .ui-table__body > .ui-table__row              ← odds por orden

_JS_EXTRACT_ODDS_ROWS = (
    "() => {"
    "  const NL = String.fromCharCode(10);"
    "  const wrapper = document.querySelector('.oddsTab__tableWrapper');"
    "  if (!wrapper) return JSON.stringify([]);"
    # bookmaker images in DOM order
    "  const imgs = Array.from(wrapper.querySelectorAll('img[alt]'))"
    "    .filter(img => (img.src || '').includes('bookmakers'));"
    # odds rows: only rows with at least one number > 1
    "  const oddsRows = Array.from(wrapper.querySelectorAll('.ui-table__row'))"
    "    .map(r => (r.innerText || '').trim().split(NL).map(s => s.trim()))"
    "    .filter(parts => parts.some(p => parseFloat(p) > 1.0));"
    "  const result = [];"
    "  const count = Math.min(imgs.length, oddsRows.length);"
    "  for (let i = 0; i < count; i++) {"
    "    const nums = oddsRows[i].filter(p => parseFloat(p) > 1.0 && !isNaN(parseFloat(p)));"
    "    if (nums.length >= 2) {"
    "      result.push({ bookmaker: imgs[i].alt, odds: nums });"
    "    }"
    "  }"
    "  return JSON.stringify(result);"
    "}"
)


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_flashscore_feed(raw: str) -> list[dict[str, str]]:
    """Convierte el texto propietario de Flashscore en una lista de partidos."""
    events: list[dict[str, str]] = []

    for segment in raw.split(_RECORD_SEP):
        fields: dict[str, str] = {}
        # Cada campo tiene formato:  KEY÷VALUE¬
        for chunk in segment.split(_FIELD_END):
            if _FIELD_SEP in chunk:
                key, _, val = chunk.partition(_FIELD_SEP)
                if key.strip():
                    fields[key.strip()] = val.strip()

        if "AA" not in fields:
            continue

        # AA=id, CX=home (o AE como fallback), AF=away, AD=timestamp
        home = fields.get("CX") or fields.get("AE") or "?"
        away = fields.get("AF") or "?"
        ts = fields.get("AD") or ""

        events.append({
            "id": fields["AA"],
            "home": home,
            "away": away,
            "ts": ts,
        })

    return events


def _book_odds_to_outcomes(
    book_odds: list[dict[str, object]], home: str, away: str
) -> list[Outcome]:
    """Convierte [{bookmaker, odds: [str, ...]}, ...] en Outcomes del dominio.

    El JS de Flashscore ya separó nombres de bookmakers de sus cuotas.
    Parámetros:
      book_odds  — lista de dicts {'bookmaker': str, 'odds': list[str]}
      home/away  — nombres de los equipos para etiquetar las cuotas 1/2
    """
    outcomes: list[Outcome] = []

    for item in book_odds:
        bookmaker = str(item.get("bookmaker") or "").strip()
        raw_odds = item.get("odds") or []
        if not bookmaker or not isinstance(raw_odds, list):
            continue

        nums = []
        for o in raw_odds:
            try:
                p = float(str(o))
                if 1.0 < p < 500.0:
                    nums.append(p)
            except (ValueError, TypeError):
                continue

        if len(nums) < 2:
            continue

        labels = [home, "Empate", away] if len(nums) >= 3 else [home, away]
        for label, price in zip(labels, nums[:3], strict=False):
            outcomes.append(Outcome(name=label, bookmaker=bookmaker, price=price))

    logger.debug(
        "Scraper: %d outcomes de %d bookmakers", len(outcomes), len(book_odds)
    )
    return outcomes
