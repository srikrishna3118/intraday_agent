import logging
import os
import sys
from datetime import datetime


def setup_logger(name=None) -> logging.Logger:
    """Configure console + daily file logging."""
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger(name)

    root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        os.path.join(log_dir, f"trading_{datetime.now():%Y%m%d}.log")
    )
    file_handler.setFormatter(fmt)

    error_handler = logging.FileHandler(
        os.path.join(log_dir, f"errors_{datetime.now():%Y%m%d}.log")
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    root.addHandler(file_handler)
    root.addHandler(error_handler)
    root.addHandler(console)

    return logging.getLogger(name)


def log_trade(action: str, symbol: str, quantity: int, price: float, result: dict) -> None:
    logger = logging.getLogger("trade")
    payload = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "result": result,
    }
    if result.get("success"):
        logger.info("TRADE: %s", payload)
    else:
        logger.error("TRADE FAILED: %s", payload)
