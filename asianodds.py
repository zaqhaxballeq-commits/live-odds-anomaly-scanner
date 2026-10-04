\
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

LOGIN_URL = "https://webapi.asianodds88.com/AsianOddsService/Login"


class AsianOddsError(RuntimeError):
    pass


class AsianOddsClient:
    def __init__(self, username: str, password: str, password_is_md5: bool = False):
        self.username = username
        self.password = password
        self.password_is_md5 = password_is_md5

        self.http = requests.Session()
        self.http.headers.update({"Accept": "application/json"})
        self.token: Optional[str] = None
        self.key: Optional[str] = None
        self.service_url: Optional[str] = None
        self._auth_lock = threading.Lock()

    def _password_hash(self) -> str:
        if self.password_is_md5:
            return self.password.lower()
        return hashlib.md5(self.password.encode("utf-8")).hexdigest()

    def login_and_register(self) -> None:
        if not self.username or not self.password:
            raise AsianOddsError("Brak AO_USERNAME lub AO_PASSWORD.")

        with self._auth_lock:
            response = self.http.get(
                LOGIN_URL,
                params={"username": self.username, "password": self._password_hash()},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()

            if payload.get("Code") != 0:
                raise AsianOddsError(f"Login AsianOdds failed: {payload}")

            result = payload.get("Result") or {}
            if not result.get("SuccessfulLogin"):
                raise AsianOddsError(
                    f"Login AsianOdds rejected: {result.get('TextMessage', 'unknown error')}"
                )

            token = str(result.get("Token") or "")
            key = str(result.get("Key") or "")
            service_url = str(result.get("Url") or "").rstrip("/")

            if not token or not key or not service_url:
                raise AsianOddsError("Login response is missing Token/Key/Url.")

            reg = self.http.get(
                f"{service_url}/Register",
                params={"username": self.username},
                headers={"AOToken": token, "AOKey": key, "Accept": "application/json"},
                timeout=20,
            )
            reg.raise_for_status()
            reg_payload = reg.json()

            if reg_payload.get("Code") != 0:
                raise AsianOddsError(f"AsianOdds Register failed: {reg_payload}")

            reg_result = reg_payload.get("Result") or {}
            if not reg_result.get("Success"):
                raise AsianOddsError(
                    f"AsianOdds Register rejected: {reg_result.get('TextMessage', 'unknown error')}"
                )

            self.token = token
            self.key = key
            self.service_url = service_url
            log.info("AsianOdds authenticated and registered. service_url=%s", service_url)

    def _ensure_auth(self) -> None:
        if not self.token or not self.service_url:
            self.login_and_register()

    def _get(self, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self._ensure_auth()
        assert self.service_url and self.token

        response = self.http.get(
            f"{self.service_url}/{method}",
            params=params or {},
            headers={"AOToken": self.token, "Accept": "application/json"},
            timeout=25,
        )

        if response.status_code in (401, 403):
            log.warning("AsianOdds HTTP %s. Re-authenticating.", response.status_code)
            self.login_and_register()
            assert self.service_url and self.token
            response = self.http.get(
                f"{self.service_url}/{method}",
                params=params or {},
                headers={"AOToken": self.token, "Accept": "application/json"},
                timeout=25,
            )

        response.raise_for_status()
        payload = response.json()

        if payload.get("Code") != 0:
            text = str(payload)
            # Sessions can expire or be invalidated by IP changes. Re-auth once.
            if any(x in text.lower() for x in ("login", "token", "author", "session", "register")):
                log.warning("AsianOdds API rejected session. Re-authenticating.")
                self.login_and_register()
                assert self.service_url and self.token
                retry = self.http.get(
                    f"{self.service_url}/{method}",
                    params=params or {},
                    headers={"AOToken": self.token, "Accept": "application/json"},
                    timeout=25,
                )
                retry.raise_for_status()
                payload = retry.json()

        if payload.get("Code") != 0:
            raise AsianOddsError(f"{method} failed: {payload}")

        return payload

    def get_bookies(self) -> list[dict[str, Any]]:
        payload = self._get("GetBookies")
        data = payload.get("Data")
        return data if isinstance(data, list) else []

    def get_live_feeds(self, since: Optional[int] = None) -> tuple[Optional[int], list[dict[str, Any]]]:
        params: dict[str, Any] = {
            "sportsType": 1,       # football
            "marketTypeId": 0,    # LIVE only
            "bookies": "ALL",
            "leagues": "ALL",
            "oddsFormat": "00",    # decimal / European
        }
        if since is not None:
            params["since"] = int(since)

        payload = self._get("GetFeeds", params=params)
        result = payload.get("Result") or {}
        new_since = result.get("Since")

        games: list[dict[str, Any]] = []
        sports = result.get("Sports") or []
        if isinstance(sports, dict):
            sports = [sports]

        for sport in sports:
            match_games = (sport or {}).get("MatchGames") or []
            if isinstance(match_games, dict):
                match_games = [match_games]
            for game in match_games:
                if isinstance(game, dict):
                    games.append(game)

        return (int(new_since) if new_since is not None else since), games
