#!/usr/bin/env python3
"""CLI entry point for the intraday RSI+volume agent."""

import argparse
import fcntl
import os
import sys

from intraday_agent.agent import IntradayAgent
from intraday_agent.config import Config
from intraday_agent.logging_setup import setup_logger


def _acquire_single_instance() -> None:
    """Refuse to start if another run_agent.py loop is already running."""
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    lock_path = os.path.join(Config.DATA_DIR, "run_agent.lock")
    lock_file = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(
            "Another run_agent.py is already running. "
            "Stop it first: pkill -INT -f 'python run_agent.py'",
            file=sys.stderr,
        )
        sys.exit(1)
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    # Keep lock_file open for process lifetime (held by caller's scope via return)
    _acquire_single_instance._lock_file = lock_file  # type: ignore[attr-defined]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Autonomous Nifty 50 RSI+volume mean-reversion intraday agent (Angel One)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan/manage cycle then exit",
    )
    args = parser.parse_args()

    setup_logger()
    Config.validate()

    if not args.once:
        _acquire_single_instance()

    agent = IntradayAgent()

    if args.once:
        if agent.is_market_open():
            agent.run_once()
        else:
            print("Market is closed.")
        return 0

    agent.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
