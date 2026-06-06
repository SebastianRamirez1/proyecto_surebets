from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


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
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    active_connections: list[WebSocket] = []

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

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        active_connections.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            active_connections.remove(websocket)

    async def broadcast(opportunity: Any) -> None:
        data = json.dumps(_serialize_opp(opportunity))
        dead = []
        for ws in active_connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            active_connections.remove(ws)

    app.state.broadcast = broadcast

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


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
