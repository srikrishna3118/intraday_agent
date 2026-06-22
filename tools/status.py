#!/usr/bin/env python3
"""Health check for the intraday agent setup."""

import os
import sys
from datetime import datetime


def check(path: str) -> bool:
    return os.path.exists(path)


def main() -> int:
    print("\n" + "=" * 60)
    print("Intraday Agent — Health Check")
    print("=" * 60)
    print(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}\n")

    checks = [
        ("intraday_agent package", check("intraday_agent/agent.py")),
        ("run_agent.py", check("run_agent.py")),
        ("requirements.txt", check("requirements.txt")),
        (".env.example", check(".env.example")),
    ]

    ok = True
    for name, result in checks:
        status = "OK" if result else "FAIL"
        print(f"  [{status}] {name}")
        ok = ok and result

    if not check(".env"):
        print("  [FAIL] .env — copy from .env.example and add Angel credentials")
        ok = False
    else:
        with open(".env") as fh:
            content = fh.read()
        if "your_api_key_here" in content:
            print("  [WARN] .env still has placeholder credentials")
        else:
            print("  [OK]   .env present")

    print("\n" + "=" * 60)
    if ok:
        print("Ready. Run: python run_agent.py")
        print("Paper mode default — set LIVE_TRADING=true for real orders.")
    else:
        print("Fix the issues above before running.")
    print("=" * 60 + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
