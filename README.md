# Sports Arbitrage Detector

Motor en tiempo real que detecta **sure bets** (oportunidades de arbitraje deportivo) entre casas de apuestas, notifica por Telegram y muestra las oportunidades activas en un dashboard web en vivo.

---

## Qué hace

1. Consulta cuotas de varias casas de apuestas vía API (The Odds API, OddsPapi) o scraping de agregadores públicos como OddsPortal.
2. Detecta mercados donde la suma de probabilidades implícitas de las mejores cuotas cae por debajo de 1 → arbitraje garantizado.
3. Calcula el reparto óptimo del capital para igualar el retorno en todas las patas.
4. Notifica cada nueva oportunidad por Telegram.
5. Expone un dashboard web (FastAPI + WebSocket) que actualiza las cards en tiempo real.

### Matemática

```
arb% = Σ (1 / mejor_cuota_i)   para cada resultado i

  arb% ≥ 1.0  → no hay arbitraje
  arb% < 1.0  → sure bet; beneficio = (1 / arb%) − 1

stake_i = capital · (1/cuota_i) / arb%
```

---

## Arquitectura

```
infrastructure/  ←  providers (The Odds API / OddsPapi / scraper / mock)
                     notifiers (Telegram)
                     web (FastAPI + WebSocket + dashboard)
        ↓ implementan puertos del dominio
application/     ←  ScanForArbitrageUseCase
        ↓
domain/          ←  models, ArbitrageCalculator, Protocol ports
```

---

## Configuración

Copia `.env.example` a `.env` y rellena:

```env
THE_ODDS_API_KEY=   # de https://the-odds-api.com (plan gratuito: 500 req/mes)
TELEGRAM_BOT_TOKEN= # de @BotFather en Telegram → /newbot
TELEGRAM_CHAT_ID=   # ID del chat; consulta /getUpdates con tu token
ODDS_PROVIDER=mock  # mock | the_odds_api | oddspapi | scraper
MIN_PROFIT_MARGIN=0.01
TOTAL_STAKE=1000
SCAN_INTERVAL=60
SPORTS=soccer,tennis
```

### Obtener credenciales

**Telegram:**
1. Habla con `@BotFather` → `/newbot` → copia el token.
2. Escríbele algo a tu bot.
3. Abre `https://api.telegram.org/bot<TOKEN>/getUpdates` → busca `chat.id`.

**The Odds API:**
1. Regístrate en https://the-odds-api.com → plan gratuito.
2. Copia la API key en `.env`.

---

## Ejecución

### Modo mock (sin credenciales)

```bash
pip install -e ".[dev]"
cp .env.example .env          # ODDS_PROVIDER=mock por defecto
python -m sports_arb.main     # loop de consola
# o para el dashboard:
uvicorn sports_arb.infrastructure.web.server:app --reload
# abre http://localhost:8000
```

### Tests

```bash
pytest --tb=short
```

### Docker

```bash
cp .env.example .env   # ajusta variables
docker compose up --build
# dashboard en http://localhost:8000
```

---

## Stack

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| HTTP async | httpx |
| API web | FastAPI + uvicorn |
| Tiempo real | WebSocket |
| Frontend | HTML + CSS + JS vanilla |
| Notificación | Telegram Bot API |
| Config | pydantic-settings |
| Tests | pytest + pytest-asyncio |
| Calidad | ruff + mypy |
| Contenedor | Docker + docker-compose |
| CI/CD | GitHub Actions |
