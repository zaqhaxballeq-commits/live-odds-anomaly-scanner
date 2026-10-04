\
from anomaly_engine import AnomalyEngine

def game(odds_home: float, odds_away: float, odds_draw: float, score=(0,0), minute=63):
    return {
        "IsLive": 1,
        "IsActive": True,
        "WillBeRemoved": False,
        "GameId": 123,
        "MatchId": 456,
        "LeagueName": "TEST REGIONAL LEAGUE",
        "InGameMinutes": minute,
        "FullTimeFavoured": 1,
        "HomeTeam": {"Name": "Alpha", "Score": score[0], "RedCards": 0},
        "AwayTeam": {"Name": "Beta", "Score": score[1], "RedCards": 0},
        "FullTimeOneXTwo": {
            "BookieOdds": (
                f"PIN={odds_home},{odds_away},{odds_draw};"
                f"SBO={odds_home*1.01},{odds_away},{odds_draw};"
                f"SIN={odds_home*0.99},{odds_away},{odds_draw}"
            )
        },
        "FullTimeHdp": {
            "BookieOdds": "PIN=1.95,1.95;SBO=1.96,1.94;SIN=1.94,1.96",
            "Handicap": "0.0",
        },
        "FullTimeOu": {
            "BookieOdds": "PIN=1.95,1.95;SBO=1.96,1.94;SIN=1.94,1.96",
            "Goal": "2.5",
        },
    }

def test_detects_silent_multi_bookie_move():
    engine = AnomalyEngine(min_alert_score=55, min_confirming_bookie_count=2)
    assert engine.ingest(game(3.10, 2.40, 3.10), now=1000, allow_alert=False) == []
    alerts = engine.ingest(game(2.30, 3.20, 3.20), now=1060, allow_alert=True)
    assert alerts, "Expected an anomaly alert"
    a = alerts[0]
    assert a.selection == "HOME"
    assert a.market == "1X2"
    assert a.score >= 55

def test_suppresses_after_goal():
    engine = AnomalyEngine(min_alert_score=40, min_confirming_bookie_count=2)
    engine.ingest(game(3.10, 2.40, 3.10, score=(0,0)), now=1000, allow_alert=False)
    alerts = engine.ingest(game(2.00, 4.00, 3.50, score=(1,0)), now=1060, allow_alert=True)
    assert alerts == []

if __name__ == "__main__":
    test_detects_silent_multi_bookie_move()
    test_suppresses_after_goal()
    print("OK - anomaly engine tests passed")
