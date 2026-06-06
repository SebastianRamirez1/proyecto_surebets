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
        lines = [
            f"<b>Sure Bet detectada</b>",
            f"Partido: {opp.market.label}",
            f"Deporte: {opp.market.sport}",
            f"Margen: <b>{margin_pct:.2f}%</b>",
            f"Beneficio estimado: {profit:.2f} (stake total: {opp.total_stake:.0f})",
            "",
            "Apuestas:",
        ]
        for bet in opp.bets:
            lines.append(
                f"  • {bet.outcome_name} @ {bet.price} en {bet.bookmaker} "
                f"— stake: {bet.stake:.2f} ({bet.stake_pct:.1f}%)"
            )
        return "\n".join(lines)
