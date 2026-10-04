\
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import math
import re
import time
from typing import Any, Deque, Iterable, Optional

WINDOWS = (15, 30, 60, 180, 300)
HISTORY_SECONDS = 390

LOW_INFO_PATTERNS = (
    " U19", " U20", " U21", " U23", " YOUTH", " RESERVE", " RESERVES",
    " REGIONAL", " DEVELOPMENT", " ACADEMY", " WOMEN", "WOMEN'S",
    " AMATEUR", " AMATEURS", " FRIENDLY", "FRIENDLIES",
)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def average_asian_line(raw: Any) -> Optional[float]:
    """Converts '0-0.5' -> 0.25, '0.5-1' -> 0.75, '2.5' -> 2.5."""
    if raw is None:
        return None
    txt = str(raw).strip()
    if not txt:
        return None
    nums = re.findall(r"-?\d+(?:\.\d+)?", txt)
    if not nums:
        return None
    vals = [float(x) for x in nums]
    return sum(vals) / len(vals)


def parse_bookie_odds(raw: Any, expected: int) -> dict[str, tuple[float, ...]]:
    out: dict[str, tuple[float, ...]] = {}
    if not isinstance(raw, str) or not raw.strip():
        return out

    for segment in raw.split(";"):
        segment = segment.strip()
        if not segment or segment.upper().startswith("BEST=") or "=" not in segment:
            continue
        bookie, values = segment.split("=", 1)
        bookie = bookie.strip().upper()
        try:
            odds = tuple(float(x.strip()) for x in values.split(",")[:expected])
        except ValueError:
            continue
        if len(odds) != expected or any(x <= 1.0 for x in odds):
            continue
        out[bookie] = odds
    return out


@dataclass
class Snapshot:
    received_at: float
    game_id: str
    match_id: str
    league: str
    home: str
    away: str
    minute: int
    home_score: int
    away_score: int
    home_red: int
    away_red: int
    active: bool
    one_x_two: dict[str, tuple[float, ...]]
    hdp: dict[str, tuple[float, ...]]
    ou: dict[str, tuple[float, ...]]
    hdp_home_line: Optional[float]
    ou_line: Optional[float]

    @property
    def score_text(self) -> str:
        return f"{self.home_score}:{self.away_score}"


@dataclass
class Alert:
    score: int
    severity: str
    market: str
    selection: str
    match_id: str
    game_id: str
    league: str
    home: str
    away: str
    minute: int
    score_text: str
    window_seconds: int
    median_move_pp: float
    max_move_pp: float
    agreeing_bookies: tuple[str, ...]
    sharp_bookies: tuple[str, ...]
    old_median_odds: float
    new_median_odds: float
    line_confirmation: str
    silent_seconds: int
    reasons: tuple[str, ...]


def snapshot_from_game(game: dict[str, Any], now: Optional[float] = None) -> Optional[Snapshot]:
    if _int(game.get("IsLive"), 0) != 1:
        return None
    if bool(game.get("WillBeRemoved")):
        return None

    home = game.get("HomeTeam") or {}
    away = game.get("AwayTeam") or {}

    game_id = str(game.get("GameId") or "")
    match_id = str(game.get("MatchId") or "")
    if not game_id or not match_id:
        return None

    one = game.get("FullTimeOneXTwo") or {}
    hdp = game.get("FullTimeHdp") or {}
    ou = game.get("FullTimeOu") or {}

    raw_hdp = average_asian_line(hdp.get("Handicap"))
    fav = _int(game.get("FullTimeFavoured"), 0)
    # Convert AsianOdds' non-negative handicap + favoured side into a HOME-perspective line.
    # Negative = home is giving handicap; positive = away is giving handicap.
    hdp_home_line = None
    if raw_hdp is not None:
        hdp_home_line = -abs(raw_hdp) if fav in (0, 1) else abs(raw_hdp)

    return Snapshot(
        received_at=now if now is not None else time.time(),
        game_id=game_id,
        match_id=match_id,
        league=str(game.get("LeagueName") or "UNKNOWN"),
        home=str(home.get("Name") or "HOME"),
        away=str(away.get("Name") or "AWAY"),
        minute=_int(game.get("InGameMinutes"), 0),
        home_score=_int(home.get("Score"), 0),
        away_score=_int(away.get("Score"), 0),
        home_red=_int(home.get("RedCards"), 0),
        away_red=_int(away.get("RedCards"), 0),
        active=bool(game.get("IsActive", True)),
        one_x_two=parse_bookie_odds(one.get("BookieOdds"), 3),
        hdp=parse_bookie_odds(hdp.get("BookieOdds"), 2),
        ou=parse_bookie_odds(ou.get("BookieOdds"), 2),
        hdp_home_line=hdp_home_line,
        ou_line=average_asian_line(ou.get("Goal")),
    )


def median(values: Iterable[float]) -> float:
    v = sorted(values)
    if not v:
        return 0.0
    n = len(v)
    m = n // 2
    return v[m] if n % 2 else (v[m - 1] + v[m]) / 2.0


class AnomalyEngine:
    def __init__(
        self,
        min_alert_score: int = 75,
        extreme_alert_score: int = 90,
        alert_cooldown_seconds: int = 120,
        event_cooldown_seconds: int = 75,
        min_confirming_bookie_count: int = 2,
        sharp_bookie_ids: frozenset[str] = frozenset({"PIN", "SBO", "SIN", "IBC", "ISN"}),
    ):
        self.min_alert_score = min_alert_score
        self.extreme_alert_score = extreme_alert_score
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self.event_cooldown_seconds = event_cooldown_seconds
        self.min_confirming_bookie_count = min_confirming_bookie_count
        self.sharp_bookie_ids = sharp_bookie_ids

        self.history: dict[str, Deque[Snapshot]] = defaultdict(deque)  # GameId -> snapshots
        self.last_match_state: dict[str, tuple[int, int, int, int]] = {}
        self.last_event_at: dict[str, float] = {}
        self.last_alert_at: dict[tuple[str, str, str], float] = {}

    def _prune(self, q: Deque[Snapshot], now: float) -> None:
        while q and now - q[0].received_at > HISTORY_SECONDS:
            q.popleft()

    def ingest(self, game: dict[str, Any], now: Optional[float] = None, allow_alert: bool = True) -> list[Alert]:
        now = now if now is not None else time.time()
        snap = snapshot_from_game(game, now)
        if snap is None:
            return []

        state = (snap.home_score, snap.away_score, snap.home_red, snap.away_red)
        prev_state = self.last_match_state.get(snap.match_id)
        if prev_state is not None and prev_state != state:
            self.last_event_at[snap.match_id] = now
        self.last_match_state[snap.match_id] = state

        q = self.history[snap.game_id]
        self._prune(q, now)

        alerts: list[Alert] = []
        if allow_alert and q and snap.active:
            seconds_since_event = now - self.last_event_at.get(snap.match_id, -10_000)
            if seconds_since_event >= self.event_cooldown_seconds:
                for window in WINDOWS:
                    old = self._find_baseline(q, now, window)
                    if old is None:
                        continue
                    candidate = self._evaluate_pair(old, snap, window, now, int(seconds_since_event))
                    if candidate is not None:
                        alerts.append(candidate)

        q.append(snap)

        if not alerts:
            return []

        # Keep only strongest candidate for a game update.
        alerts.sort(key=lambda a: (a.score, abs(a.median_move_pp), len(a.agreeing_bookies)), reverse=True)
        top = alerts[0]
        key = (top.match_id, top.market, top.selection)
        last = self.last_alert_at.get(key, 0.0)
        if now - last < self.alert_cooldown_seconds:
            return []
        self.last_alert_at[key] = now
        return [top]

    def _find_baseline(self, q: Deque[Snapshot], now: float, window: int) -> Optional[Snapshot]:
        if not q:
            return None
        target = now - window
        candidates = [s for s in q if now - s.received_at >= min(10, window * 0.65)]
        if not candidates:
            return None
        return min(candidates, key=lambda s: abs(s.received_at - target))

    def _evaluate_pair(
        self, old: Snapshot, cur: Snapshot, window: int, now: float, silent_seconds: int
    ) -> Optional[Alert]:
        if old.match_id != cur.match_id:
            return None

        # If a score/red-card event happened inside this comparison period, reject.
        if (
            old.home_score != cur.home_score
            or old.away_score != cur.away_score
            or old.home_red != cur.home_red
            or old.away_red != cur.away_red
        ):
            return None

        candidates: list[Alert] = []
        candidates.extend(self._market_candidates("1X2", old.one_x_two, cur.one_x_two, old, cur, window, silent_seconds))
        candidates.extend(self._market_candidates("AH", old.hdp, cur.hdp, old, cur, window, silent_seconds))
        candidates.extend(self._market_candidates("OU", old.ou, cur.ou, old, cur, window, silent_seconds))

        if not candidates:
            return None
        return max(candidates, key=lambda a: (a.score, abs(a.median_move_pp), len(a.agreeing_bookies)))

    def _market_candidates(
        self,
        market: str,
        old_map: dict[str, tuple[float, ...]],
        new_map: dict[str, tuple[float, ...]],
        old: Snapshot,
        cur: Snapshot,
        window: int,
        silent_seconds: int,
    ) -> list[Alert]:
        labels = {
            "1X2": ("HOME", "AWAY", "DRAW"),
            "AH": ("HOME", "AWAY"),
            "OU": ("OVER", "UNDER"),
        }[market]

        common = sorted(set(old_map) & set(new_map))
        if len(common) < self.min_confirming_bookie_count:
            return []

        out: list[Alert] = []
        for idx, label in enumerate(labels):
            moves: dict[str, float] = {}
            old_odds: list[float] = []
            new_odds: list[float] = []

            for bookie in common:
                try:
                    o = old_map[bookie][idx]
                    n = new_map[bookie][idx]
                except (IndexError, TypeError):
                    continue
                if o <= 1.0 or n <= 1.0:
                    continue
                # Positive = this outcome became more likely according to price.
                delta_pp = ((1.0 / n) - (1.0 / o)) * 100.0
                moves[bookie] = delta_pp
                old_odds.append(o)
                new_odds.append(n)

            positive = {b: d for b, d in moves.items() if d >= 1.5}
            if len(positive) < self.min_confirming_bookie_count:
                continue

            med_move = median(positive.values())
            max_move = max(positive.values())
            if med_move < 2.25:
                continue

            agreeing = tuple(sorted(positive, key=lambda b: positive[b], reverse=True))
            sharps = tuple(b for b in agreeing if b in self.sharp_bookie_ids)

            score = 0
            reasons: list[str] = []

            # Magnitude
            if med_move >= 12:
                score += 28
            elif med_move >= 8:
                score += 23
            elif med_move >= 5:
                score += 17
            elif med_move >= 3:
                score += 11
            else:
                score += 6
            reasons.append(f"mediana ruchu +{med_move:.1f} pp")

            # Speed
            minutes = max(window / 60.0, 0.1)
            velocity = med_move / minutes
            if velocity >= 10:
                score += 18
                reasons.append(f"bardzo wysoka prędkość {velocity:.1f} pp/min")
            elif velocity >= 6:
                score += 13
                reasons.append(f"wysoka prędkość {velocity:.1f} pp/min")
            elif velocity >= 3:
                score += 8
                reasons.append(f"prędkość {velocity:.1f} pp/min")

            # Consensus
            if len(agreeing) >= 5:
                score += 18
            elif len(agreeing) >= 3:
                score += 13
            elif len(agreeing) >= 2:
                score += 8
            reasons.append(f"{len(agreeing)} bukmacherów zgodnych")

            # Sharp confirmation
            if len(sharps) >= 2:
                score += 14
                reasons.append("2+ sharp books potwierdzają")
            elif len(sharps) == 1:
                score += 8
                reasons.append(f"sharp book {sharps[0]} potwierdza")

            # Silent move: we have observed no score/red-card change recently.
            if silent_seconds >= 180:
                score += 12
                reasons.append("brak zmiany wyniku/kartki przez 3+ min")
            elif silent_seconds >= 75:
                score += 8
                reasons.append("brak świeżej zmiany wyniku/kartki")

            # Low-information league heuristic (small bonus only).
            league_upper = f" {cur.league.upper()} "
            if any(pat in league_upper for pat in LOW_INFO_PATTERNS):
                score += 4
                reasons.append("liga o podwyższonym profilu informacyjnego/niska płynność")

            line_confirmation = ""
            line_bonus = 0
            if market in ("1X2", "AH"):
                if old.hdp_home_line is not None and cur.hdp_home_line is not None:
                    shift = cur.hdp_home_line - old.hdp_home_line
                    if label == "HOME" and shift <= -0.25:
                        line_bonus = 12
                        line_confirmation = f"AH HOME {old.hdp_home_line:+.2f} → {cur.hdp_home_line:+.2f}"
                    elif label == "AWAY" and shift >= 0.25:
                        line_bonus = 12
                        line_confirmation = f"AH AWAY shift {old.hdp_home_line:+.2f} → {cur.hdp_home_line:+.2f}"
            elif market == "OU":
                if old.ou_line is not None and cur.ou_line is not None:
                    shift = cur.ou_line - old.ou_line
                    if label == "OVER" and shift >= 0.25:
                        line_bonus = 12
                        line_confirmation = f"O/U {old.ou_line:.2f} → {cur.ou_line:.2f}"
                    elif label == "UNDER" and shift <= -0.25:
                        line_bonus = 12
                        line_confirmation = f"O/U {old.ou_line:.2f} → {cur.ou_line:.2f}"

            if line_bonus:
                score += line_bonus
                reasons.append("zmiana linii potwierdza kierunek")

            score = min(100, score)
            if score < self.min_alert_score:
                continue

            severity = "EXTREME" if score >= self.extreme_alert_score else "HIGH"
            out.append(
                Alert(
                    score=score,
                    severity=severity,
                    market=market,
                    selection=label,
                    match_id=cur.match_id,
                    game_id=cur.game_id,
                    league=cur.league,
                    home=cur.home,
                    away=cur.away,
                    minute=cur.minute,
                    score_text=cur.score_text,
                    window_seconds=window,
                    median_move_pp=med_move,
                    max_move_pp=max_move,
                    agreeing_bookies=agreeing,
                    sharp_bookies=sharps,
                    old_median_odds=median(old_odds),
                    new_median_odds=median(new_odds),
                    line_confirmation=line_confirmation,
                    silent_seconds=silent_seconds,
                    reasons=tuple(reasons),
                )
            )

        return out
