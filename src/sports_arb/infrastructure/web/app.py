from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


class _ConnPrefs:
    """Per-WebSocket connection preferences (capital + bookmaker filter)."""

    __slots__ = ("capital", "bookmakers")

    def __init__(self) -> None:
        self.capital: float | None = None
        self.bookmakers: frozenset[str] = frozenset()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' ws: wss:;"
        )
        return response


def create_app(use_case: Any = None) -> FastAPI:
    app = FastAPI(title="Sports Arbitrage Detector", docs_url=None, redoc_url=None)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    active_connections: list[WebSocket] = []
    conn_prefs: dict[int, _ConnPrefs] = {}

    # ── REST endpoints ────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        index = STATIC_DIR / "index.html"
        return HTMLResponse(content=index.read_text(encoding="utf-8"))

    @app.get("/api/opportunities")
    async def get_opportunities() -> JSONResponse:
        if use_case is None:
            return JSONResponse(content=[])
        opps = use_case.latest_opportunities
        return JSONResponse(content=[_serialize_opp(o) for o in opps])

    @app.post("/api/scan/force")
    async def force_scan() -> JSONResponse:
        if use_case is None:
            return JSONResponse(content={"ok": False, "error": "sin use case"}, status_code=503)
        opps, cooldown = await use_case.force_scan()
        if cooldown > 0:
            return JSONResponse(
                content={"ok": False, "cooldown": cooldown,
                         "error": f"Espera {cooldown}s antes de forzar otro scan"},
                status_code=429,
            )
        await broadcast_refresh()
        return JSONResponse(content={"ok": True, "opportunities": len(opps)})

    @app.get("/api/bookmakers")
    async def get_bookmakers() -> JSONResponse:
        if use_case is None:
            return JSONResponse(content=[])
        return JSONResponse(content=use_case.known_bookmakers)

    # ── WebSocket ─────────────────────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        active_connections.append(websocket)
        prefs = _ConnPrefs()
        conn_prefs[id(websocket)] = prefs

        # Send current state immediately on connect
        if use_case is not None:
            opps = use_case.filter_opportunities()
            await websocket.send_text(
                json.dumps({"type": "refresh", "opportunities": [_serialize_opp(o) for o in opps]})
            )

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                    if msg.get("type") == "prefs":
                        _apply_prefs(msg, prefs)
                        if use_case is not None:
                            allowed = prefs.bookmakers if prefs.bookmakers else None
                            opps = use_case.filter_opportunities(prefs.capital, allowed)
                            await websocket.send_text(
                                json.dumps({
                                    "type": "refresh",
                                    "opportunities": [_serialize_opp(o) for o in opps],
                                })
                            )
                except (json.JSONDecodeError, ValueError, KeyError):
                    pass
        except WebSocketDisconnect:
            active_connections.remove(websocket)
            conn_prefs.pop(id(websocket), None)

    # ── Broadcast (called from scan loop) ────────────────────────────────────

    async def broadcast_refresh() -> None:
        if not use_case:
            return
        dead: list[WebSocket] = []
        for ws in active_connections:
            prefs = conn_prefs.get(id(ws), _ConnPrefs())
            allowed = prefs.bookmakers if prefs.bookmakers else None
            try:
                opps = use_case.filter_opportunities(prefs.capital, allowed)
                data = json.dumps({
                    "type": "refresh",
                    "opportunities": [_serialize_opp(o) for o in opps],
                })
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in active_connections:
                active_connections.remove(ws)
            conn_prefs.pop(id(ws), None)

    app.state.broadcast_refresh = broadcast_refresh

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_prefs(msg: dict[str, Any], prefs: _ConnPrefs) -> None:
    if "capital" in msg:
        raw = msg["capital"]
        try:
            cap = float(raw) if raw is not None else 0.0
            prefs.capital = cap if cap > 0 else None
        except (TypeError, ValueError):
            prefs.capital = None
    if "bookmakers" in msg:
        bks = msg["bookmakers"]
        prefs.bookmakers = (
            frozenset(str(b) for b in bks) if isinstance(bks, list) and bks
            else frozenset()
        )


def _serialize_opp(opp: Any) -> dict[str, Any]:
    return {
        "event_id": opp.market.event_id,
        "label": opp.market.label,
        "sport": opp.market.sport,
        "profit_margin_pct": round(opp.profit_margin * 100, 2),
        "profit_amount": round(opp.profit_amount, 2),
        "total_stake": opp.total_stake,
        "arb_percentage": round(opp.arb_percentage, 6),
        "detected_at": opp.detected_at.isoformat(),
        "bets": [
            {
                "outcome": b.outcome_name,
                "bookmaker": b.bookmaker,
                "price": b.price,
                "stake": b.stake,
                "stake_pct": b.stake_pct,
                "guaranteed_return": round(b.guaranteed_return, 2),
            }
            for b in opp.bets
        ],
    }
