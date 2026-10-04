\
from __future__ import annotations

import html
import logging
import requests

from anomaly_engine import Alert

log = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, alert: Alert) -> bool:
        if not self.enabled:
            log.info("Telegram disabled; alert not sent.")
            return False

        icon = "🚨🚨" if alert.severity == "EXTREME" else "🚨"
        sharp = ", ".join(alert.sharp_bookies) if alert.sharp_bookies else "brak oznaczonych"
        books = ", ".join(alert.agreeing_bookies)
        line = f"\n📏 <b>Line:</b> {html.escape(alert.line_confirmation)}" if alert.line_confirmation else ""
        reasons = "\n".join(f"• {html.escape(x)}" for x in alert.reasons)

        text = (
            f"{icon} <b>LIVE MARKET ANOMALY — {alert.score}/100</b>\n\n"
            f"🏆 <b>{html.escape(alert.league)}</b>\n"
            f"⚽ {html.escape(alert.home)} — {html.escape(alert.away)}\n"
            f"⏱ {alert.minute}' | wynik {html.escape(alert.score_text)}\n\n"
            f"📊 <b>{alert.market} / {alert.selection}</b>\n"
            f"💸 mediana kursu: <b>{alert.old_median_odds:.3f} → {alert.new_median_odds:.3f}</b>\n"
            f"📈 implied move: <b>+{alert.median_move_pp:.2f} pp</b> "
            f"(max +{alert.max_move_pp:.2f} pp)\n"
            f"🕒 okno: {alert.window_seconds}s\n"
            f"🤝 zgodne booki: {html.escape(books)}\n"
            f"🎯 sharp: {html.escape(sharp)}"
            f"{line}\n\n"
            f"<b>Dlaczego:</b>\n{reasons}\n\n"
            f"⚠️ To sygnał anomalii rynku, nie dowód manipulacji meczem."
        )

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if not r.ok:
                log.error("Telegram error %s: %s", r.status_code, r.text[:500])
                return False
            return True
        except requests.RequestException:
            log.exception("Telegram request failed.")
            return False
