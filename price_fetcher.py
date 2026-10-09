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
        f"🕒 *Updated:* {timestamp}"
    )


def send_telegram_message(text: str, token: str | None = None, chat_ids: str | None = None) -> None:
    """Post a Markdown message to every chat listed in CHAT_IDS.

    CHAT_IDS is a comma-separated string, for example
    "-100123456789,-1004482091161". A failure for one chat is printed and
    does not stop delivery to the remaining chats.
    """
    token = token or os.getenv("TELEGRAM_TOKEN", "")
    raw_ids = chat_ids if chat_ids is not None else os.getenv("CHAT_IDS", "")
    ids = [chat_id.strip() for chat_id in raw_ids.split(",") if chat_id.strip()]
    if not token or not ids:
        raise RuntimeError("Set TELEGRAM_TOKEN and CHAT_IDS before sending.")

    for chat_id in ids:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
                timeout=20,
            )
            if response.status_code != 200:
                print(f"Failed to send to {chat_id}: HTTP {response.status_code} {response.text}")
                continue
            payload = response.json()
            if not payload.get("ok"):
                description = payload.get("description", "Telegram API rejected the message.")
                print(f"Failed to send to {chat_id}: {description}")
        except requests.RequestException as exc:
            print(f"Failed to send to {chat_id}: {exc}")


def main() -> None:
    """Print the price message and send it when Telegram credentials are set."""
    # Windows consoles often default to cp1252, which cannot print the emoji.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    message = get_formatted_message()
    print(message)

    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_ids = os.getenv("CHAT_IDS", "")
    if token and chat_ids:
        send_telegram_message(message, token, chat_ids)
        return

    # Scheduled runs must fail loudly if the repo secrets were not configured.
    if os.getenv("CI"):
        raise SystemExit("Set TELEGRAM_TOKEN and CHAT_IDS to send notifications.")


if __name__ == "__main__":
    main()
