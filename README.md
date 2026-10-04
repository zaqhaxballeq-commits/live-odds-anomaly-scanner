\
# LIVE Odds Anomaly Scanner

MVP skanera wyłącznie dla piłki nożnej LIVE na feedzie AsianOdds.

## Co robi

- odpytuje AsianOdds `GetFeeds` tylko dla `marketTypeId=0` (LIVE),
- używa `since`, więc po pierwszym pobraniu dostaje tylko aktualizacje,
- pracuje na kursach dziesiętnych (`oddsFormat=00`),
- analizuje 1X2, Asian Handicap i Over/Under,
- liczy zmianę implied probability w oknach 15 / 30 / 60 / 180 / 300 s,
- wymaga zgodnego ruchu kilku bukmacherów,
- daje dodatkową wagę oznaczonym sharp books,
- blokuje alert po wykrytej zmianie wyniku lub czerwonej kartki,
- wysyła Telegram tylko dla score >= `MIN_ALERT_SCORE`,
- nie stawia zakładów i nie określa meczu jako ustawionego.

## Ważne ograniczenie wersji 1

AsianOdds daje wynik i czerwone kartki, ale ten projekt nie ma jeszcze osobnego event-feed dla:
VAR, rzutu karnego, kontuzji, anulowanego gola czy innych wydarzeń live.
Dlatego alert oznacza "anomalię rynku", nie dowód manipulacji.

## Uruchomienie lokalne

Python 3.11+.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env
# Uzupełnij .env
python test_engine.py
python bot.py
```

Health:
`http://localhost:10000/health`

## Zmienne środowiskowe

Najważniejsze:

- `AO_USERNAME`
- `AO_PASSWORD`
- `AO_PASSWORD_IS_MD5=false`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Skan:
- `SCAN_SECONDS=5.2`
- `MIN_ALERT_SCORE=75`
- `EXTREME_ALERT_SCORE=90`
- `ALERT_COOLDOWN_SECONDS=120`
- `EVENT_COOLDOWN_SECONDS=75`
- `MIN_CONFIRMING_BOOKIE_COUNT=2`
- `SHARP_BOOKIE_IDS=PIN,SBO,SIN,IBC,ISN`

## Render

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
gunicorn bot:app --workers 1 --threads 4 --timeout 120
```

Ustaw wszystkie zmienne z `.env.example` w Render -> Environment.

**Używaj jednego workera**, bo skaner działa w tle procesu aplikacji.
Przy wielu workerach uruchomiłbyś kilka równoległych scannerów.

## Logika score

Score rośnie za:
- duży ruch implied probability,
- wysoką szybkość ruchu,
- zgodność 2/3/5+ bukmacherów,
- potwierdzenie przez sharp books,
- brak świeżej zmiany wyniku/czerwonej kartki,
- zgodną zmianę linii AH / O-U, jeśli API zmieni linię w tym samym GameId,
- mały bonus dla lig o niższej przejrzystości / płynności.

Pierwszy pełny snapshot jest tylko baseline — bot nie alertuje od razu po starcie.

## Następny etap

Po potwierdzeniu, że konto AsianOdds oddaje live feed:
1. zapisujemy surowe zmiany do Postgresa,
2. dokładamy zewnętrzny event feed (gol/VAR/karny/kartki),
3. uczymy normalną zmienność osobno dla każdej ligi,
4. dodajemy lead/lag: który book rozpoczyna ruch.
