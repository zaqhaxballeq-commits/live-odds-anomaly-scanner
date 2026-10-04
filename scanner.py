\
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, asdict
from typing import Any

from asianodds import AsianOddsClient
from anomaly_engine import AnomalyEngine, Alert
from config import Settings
from telegram_alerts import TelegramAlerter

log = logging.getLogger(__name__)


@dataclass
class ScannerStatus:
    running: bool = False
    authenticated: bool = False
    initialized: bool = False
    last_scan_at: float | None = None
    last_error: str | None = None
    since: int | None = None
    updates_last_scan: int = 0
    total_updates: int = 0
    alerts_sent: int = 0
    available_bookies: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveScanner:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.client = AsianOddsClient(cfg.ao_username, cfg.ao_password, cfg.ao_password_is_md5)
        self.engine = AnomalyEngine(
            min_alert_score=cfg.min_alert_score,
            extreme_alert_score=cfg.extreme_alert_score,
            alert_cooldown_seconds=cfg.alert_cooldown_seconds,
            event_cooldown_seconds=cfg.event_cooldown_seconds,
            min_confirming_bookie_count=cfg.min_confirming_bookie_count,
            sharp_bookie_ids=cfg.sharp_bookie_ids,
        )
        self.telegram = TelegramAlerter(cfg.telegram_bot_token, cfg.telegram_chat_id)
        self.status = ScannerStatus(available_bookies=[])
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def _authenticate(self) -> None:
        self.client.login_and_register()
        self.status.authenticated = True
        try:
            bookies = self.client.get_bookies()
            available = [
                str(x.get("Id"))
                for x in bookies
                if x.get("IsFeedAvailable") and x.get("Id")
            ]
            self.status.available_bookies = available
            log.info("Feed-available bookies: %s", ",".join(available) or "none reported")
        except Exception as exc:
            log.warning("GetBookies failed (scanner can still continue): %s", exc)

    def run_forever(self) -> None:
        self.status.running = True
        backoff = 5.0
        log.info(
            "Starting LIVE-only scanner: interval=%.2fs min_score=%s telegram=%s",
            self.cfg.scan_seconds,
            self.cfg.min_alert_score,
            "ON" if self.telegram.enabled else "OFF",
        )

        while not self._stop.is_set():
            started = time.monotonic()
            try:
                if not self.status.authenticated:
                    self._authenticate()

                new_since, games = self.client.get_live_feeds(self.status.since)
                now = time.time()

                # First full response only builds baselines; it must not produce alerts.
                allow_alert = self.status.initialized
                alerts: list[Alert] = []

                for game in games:
                    alerts.extend(self.engine.ingest(game, now=now, allow_alert=allow_alert))

                self.status.since = new_since
                self.status.initialized = True
                self.status.last_scan_at = now
                self.status.last_error = None
                self.status.updates_last_scan = len(games)
                self.status.total_updates += len(games)

                for alert in alerts:
                    log.warning(
                        "ANOMALY score=%s %s %s - %s market=%s selection=%s books=%s",
                        alert.score, alert.league, alert.home, alert.away,
                        alert.market, alert.selection, ",".join(alert.agreeing_bookies),
                    )
                    if self.telegram.send(alert):
                        self.status.alerts_sent += 1

                backoff = 5.0

            except Exception as exc:
                self.status.last_error = f"{type(exc).__name__}: {exc}"
                self.status.authenticated = False
                log.exception("Scanner cycle failed.")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)
                continue

            elapsed = time.monotonic() - started
            sleep_for = max(0.05, self.cfg.scan_seconds - elapsed)
            self._stop.wait(sleep_for)

        self.status.running = False
