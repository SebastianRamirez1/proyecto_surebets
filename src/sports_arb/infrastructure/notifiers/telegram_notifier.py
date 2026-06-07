from __future__ import annotations

import logging

import httpx

from ...domain.models import ArbitrageOpportunity

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    async def notify(self, opportunity: ArbitrageOpportunity) -> None:
        text = self._format(opportunity)
        url = f"{_API_BASE}/bot{self._bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Fallo al enviar notificacion Telegram: %s", exc)

    def _format(self, opp: ArbitrageOpportunity) -> str:
        margin_pct = opp.profit_margin * 100
        profit = opp.profit_amount
        capital = opp.total_stake
        guaranteed = min(b.guaranteed_return for b in opp.bets)
        lines = [
            "🎯 <b>SUREBET DETECTADA</b>",
            "",
            f"⚽ {opp.market.label}  ({opp.market.sport})",
            f"📊 Margen garantizado: <b>{margin_pct:.2f}%</b>",
            (
                f"💰 Con {capital:.0f} → ganarás <b>{profit:.2f}</b>"
                " sin importar el resultado"
            ),
            "",
            "📋 <b>INSTRUCCIONES DE APUESTA:</b>",
        ]
        for i, bet in enumerate(opp.bets, 1):
            lines += [
                "",
                f"<b>— PASO {i} ——————————————————</b>",
                f"🏠 Casa:    <b>{bet.bookmaker}</b>",
                f"🎲 Apuesta: <i>{bet.outcome_name}</i>",
                f"📈 Cuota:   <b>{bet.price:.2f}</b>",
                (
                    f"💵 Monto:   <b>{bet.stake:.2f}</b>"
                    f"  ({bet.stake_pct:.1f}% de tu capital)"
                ),
                f"↩️  Recibirás si gana: {bet.guaranteed_return:.2f}",
            ]
        lines += [
            "",
            f"✅ <b>Retorno mínimo garantizado: {guaranteed:.2f}</b>",
            f"    (ganancia neta: +{profit:.2f})",
        ]
        return "\n".join(lines)
