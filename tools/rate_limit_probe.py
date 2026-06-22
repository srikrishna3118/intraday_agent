"""Calibrate Angel getCandleData rate-limit recovery.

Runs ONE isolated candle request per tick (default every 12 min) and records the
result to data/rate_probe.log. Infrequent by design — frequent probing keeps the
sticky "Access denied" penalty alive. Use the log to learn:

  * how long a penalty takes to clear after we stop hammering, and
  * (with --ramp) how many back-to-back calls the account tolerates once clear.

Usage:
  python tools/rate_limit_probe.py --interval-min 12 --until 15:30
  python tools/rate_limit_probe.py --interval-min 12 --until 15:30 --ramp
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta

from intraday_agent.broker import AngelBroker
from intraday_agent.instruments import get_registry

PROBE_TOKEN = "2885"  # RELIANCE
PROBE_SYMBOL = "RELIANCE"
LOG_PATH = "data/rate_probe.log"


def _log(line: str) -> None:
    stamped = f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}"
    print(stamped, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(stamped + "\n")


def _single_call(broker: AngelBroker, days: int = 3, force: bool = True):
    if force:
        # Clear our client-side guard so this tick always makes a real API call.
        broker._candle_pause_until = 0.0
        broker._rate_limit_streak = 0
    end = datetime.now()
    start = end - timedelta(days=days)
    df = broker.get_candles_range(PROBE_TOKEN, start, end)
    return 0 if df is None else len(df)


def _ramp(broker: AngelBroker) -> None:
    """Once clear, find how many spaced calls succeed before a limit appears."""
    _log("RAMP start (0.4s spacing, RELIANCE)")
    ok = 0
    for i in range(1, 11):
        n = _single_call(broker)
        if n:
            ok += 1
        else:
            _log(f"RAMP broke at call #{i} (succeeded {ok} before limit)")
            return
        time.sleep(0.4)
    _log(f"RAMP completed 10/10 calls OK (>=2.5/sec sustained tolerated)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval-min", type=float, default=12.0)
    ap.add_argument("--until", default="15:30", help="HH:MM IST stop time")
    ap.add_argument("--ramp", action="store_true", help="ramp-test once clear")
    args = ap.parse_args()

    hh, mm = (int(x) for x in args.until.split(":"))

    get_registry().load()
    broker = AngelBroker()
    broker.login()
    _log(f"=== probe start interval={args.interval_min}min until={args.until} ramp={args.ramp} ===")

    cleared_once = False
    while True:
        now = datetime.now()
        if (now.hour, now.minute) >= (hh, mm):
            _log("=== probe stop (reached --until) ===")
            break

        n = _single_call(broker)
        if n:
            _log(f"PROBE OK — {n} bars. Penalty CLEAR.")
            if args.ramp and not cleared_once:
                cleared_once = True
                _ramp(broker)
        else:
            paused = broker.candle_pause_remaining()
            _log(f"PROBE FAIL — rate limited (local pause {paused:.0f}s, streak {broker.rate_limit_streak}).")

        time.sleep(args.interval_min * 60)


if __name__ == "__main__":
    main()
