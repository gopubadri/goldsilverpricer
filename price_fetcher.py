"""Fetch live gold and silver prices and format them for an Indian Telegram bot.

International futures are quoted in USD per troy ounce. This module converts
those quotes to INR per gram using the live USD/INR rate.
"""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

# 1 troy ounce = 31.1035 grams (exact conversion used by bullion markets).
TROY_OUNCE_GRAMS = 31.1035

GOLD_SYMBOL = "GC=F"
SILVER_SYMBOL = "SI=F"
USDINR_SYMBOL = "INR=X"

IST = ZoneInfo("Asia/Kolkata")

MARKET_CLOSED_MESSAGE = (
    "Market currently closed. Live gold and silver prices are unavailable "
    "right now. Please try again shortly."
)

DISCLAIMER = (
    "⚠️ *Note:* International spot rate converted to INR. "
    "Local jeweler prices may vary due to import duties & making charges."
)


def _is_valid_price(value: object) -> bool:
    """Return True when value is a finite, positive number."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _last_price(symbol: str) -> float:
    """Return the latest price without calling ticker.info.

    fast_info is preferred. Daily history is the fallback when fast_info is
    empty, which happens around session gaps and rate limits.
    """
    ticker = yf.Ticker(symbol)

    price = None
    try:
        price = ticker.fast_info.last_price
    except Exception:
        price = None

    if not _is_valid_price(price):
        history = ticker.history(period="1d")
        if history.empty or "Close" not in history.columns:
            raise ValueError(f"No price data for {symbol}")
        price = history["Close"].iloc[-1]

    if not _is_valid_price(price):
        raise ValueError(f"Invalid price for {symbol}")

    return float(price)


def usd_per_ounce_to_inr_per_gram(metal_usd: float, usd_inr: float) -> float:
    """Convert a USD-per-troy-ounce quote into INR per gram."""
    return (metal_usd * usd_inr) / TROY_OUNCE_GRAMS


def _format_inr(amount: float) -> str:
    """Format a rupee amount with Indian-style grouping and two decimals."""
    whole, fraction = f"{amount:.2f}".split(".")
    if len(whole) <= 3:
        grouped = whole
    else:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while head:
            parts.append(head[-2:])
            head = head[:-2]
        grouped = ",".join(reversed(parts)) + "," + tail
    return f"₹{grouped}.{fraction}"


def fetch_prices() -> dict[str, float]:
    """Fetch gold, silver, and USD/INR, then return INR-per-gram metal prices."""
    gold_usd = _last_price(GOLD_SYMBOL)
    silver_usd = _last_price(SILVER_SYMBOL)
    usd_inr = _last_price(USDINR_SYMBOL)

    return {
        "gold_inr_per_gram": usd_per_ounce_to_inr_per_gram(gold_usd, usd_inr),
        "silver_inr_per_gram": usd_per_ounce_to_inr_per_gram(silver_usd, usd_inr),
        "usd_inr": usd_inr,
        "gold_usd_per_oz": gold_usd,
        "silver_usd_per_oz": silver_usd,
    }


def get_formatted_message() -> str:
    """Return a Telegram Markdown message with 1g gold and silver prices in INR.

    On any fetch failure (closed market, empty data, network error) this
    returns a short notice instead of raising.
    """
    try:
        prices = fetch_prices()
    except Exception:
        return MARKET_CLOSED_MESSAGE

    timestamp = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")

    return (
        "🥇 *Gold (1g):* "
        f"{_format_inr(prices['gold_inr_per_gram'])}\n"
        "🥈 *Silver (1g):* "
        f"{_format_inr(prices['silver_inr_per_gram'])}\n"
        f"💱 *USD/INR:* {prices['usd_inr']:.2f}\n"
        f"🕒 *Updated:* {timestamp}\n\n"
        f"{DISCLAIMER}"
    )


def send_telegram_message(text: str, token: str | None = None, chat_id: str | None = None) -> None:
    """Post a Markdown message to the configured Telegram chat."""
    token = token or os.getenv("TELEGRAM_TOKEN", "")
    chat_id = chat_id or os.getenv("CHAT_ID", "")
    if not token or not chat_id:
        raise RuntimeError("Set TELEGRAM_TOKEN and CHAT_ID before sending.")

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "Telegram API rejected the message."))


def main() -> None:
    """Print the price message and send it when Telegram credentials are set."""
    # Windows consoles often default to cp1252, which cannot print the emoji.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    message = get_formatted_message()
    print(message)

    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("CHAT_ID", "")
    if token and chat_id:
        send_telegram_message(message, token, chat_id)
        return

    # Scheduled runs must fail loudly if the repo secrets were not configured.
    if os.getenv("CI"):
        raise SystemExit("Set TELEGRAM_TOKEN and CHAT_ID to send notifications.")


if __name__ == "__main__":
    main()
