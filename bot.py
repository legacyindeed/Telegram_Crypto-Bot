import os
import json
import time
import random
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ===========================
# CONFIG
# ===========================

# Either set your token here OR via environment variable BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")

POSITIONS_FILE = "positions.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

session = requests.Session()

PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
PRICE_TTL = 20

MCAP_CACHE: Dict[str, Dict[str, Any]] = {}
MCAP_TTL = 60

# Some common mappings to avoid extra CoinGecko search calls
CG_MAPPING: Dict[str, str] = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
    "ton": "the-open-network",
    "trx": "tron",
    "matic": "matic-network",
    "avax": "avalanche-2",
    "ltc": "litecoin",
    "uni": "uniswap",
    "link": "chainlink",
    "atom": "cosmos",
    "near": "near",
    "arb": "arbitrum",
    "op": "optimism",
    "sei": "sei-network",
    "inj": "injective-protocol",
    "usdc": "usd-coin",
    "usdt": "tether",
    "dai": "dai",
    "frax": "frax",
    "shib": "shiba-inu",
    "pepe": "pepe",
    "bonk": "bonk",
    "wif": "dogwifcoin",
    "flok": "floki",
}

# ===========================
# STORAGE (JSON)
# ===========================

def load_all_positions() -> Dict[str, List[Dict[str, Any]]]:
    if not os.path.exists(POSITIONS_FILE):
        return {}
    try:
        with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Error loading positions.json: {e}")
        return {}


def save_all_positions(data: Dict[str, List[Dict[str, Any]]]) -> None:
    try:
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Error saving positions.json: {e}")


def add_user_position(user_id: int, symbol: str, amount: float, buy_price: float) -> None:
    all_data = load_all_positions()
    key = str(user_id)
    all_data.setdefault(key, []).append(
        {
            "symbol": symbol.upper(),
            "amount": amount,
            "buy_price": buy_price,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
    )
    save_all_positions(all_data)


def get_user_positions(user_id: int) -> List[Dict[str, Any]]:
    all_data = load_all_positions()
    return all_data.get(str(user_id), [])


# ===========================
# HTTP + COINGECKO HELPERS
# ===========================

def safe_get(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Optional[requests.Response]:
    """Simple wrapper to avoid crashes on HTTP errors."""
    try:
        r = session.get(url, params=params, timeout=timeout)
    except Exception as e:
        logger.warning(f"Request error for {url}: {e}")
        return None

    if r.status_code != 200:
        logger.warning(f"{url} returned status {r.status_code}")
        return None

    return r


def resolve_token_id(symbol: str) -> Optional[str]:
    sym = symbol.lower().strip()
    if sym in CG_MAPPING:
        return CG_MAPPING[sym]

    url = "https://api.coingecko.com/api/v3/search"
    r = safe_get(url, params={"query": sym})
    if r is None:
        return None

    try:
        coins = (r.json() or {}).get("coins", [])
    except Exception:
        return None

    if not coins:
        return None

    for c in coins:
        if c.get("symbol", "").lower() == sym:
            return c.get("id")

    return coins[0].get("id")


def get_token_name(symbol: str) -> Optional[str]:
    token_id = resolve_token_id(symbol)
    if not token_id:
        return None

    url = f"https://api.coingecko.com/api/v3/coins/{token_id}"
    r = safe_get(url)
    if r is None:
        return None

    try:
        return (r.json() or {}).get("name")
    except Exception:
        return None


def get_current_price_usd(symbol: str) -> Optional[float]:
    sym_up = symbol.upper()
    now = time.time()
    cached = PRICE_CACHE.get(sym_up)
    if cached and now - cached["ts"] < PRICE_TTL:
        return cached["price"]

    token_id = resolve_token_id(symbol)
    if not token_id:
        return None

    url = "https://api.coingecko.com/api/v3/simple/price"
    r = safe_get(url, params={"ids": token_id, "vs_currencies": "usd"})
    if r is None:
        return None

    try:
        data = r.json()
        price = data.get(token_id, {}).get("usd")
    except Exception:
        return None

    if price is None:
        return None

    PRICE_CACHE[sym_up] = {"price": price, "ts": now}
    return price


def get_historical_price_usd(symbol: str, date_str: str) -> Optional[float]:
    token_id = resolve_token_id(symbol)
    if not token_id:
        return None

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        cg_date = dt.strftime("%d-%m-%Y")
    except ValueError:
        return None

    url = f"https://api.coingecko.com/api/v3/coins/{token_id}/history"
    r = safe_get(url, params={"date": cg_date})
    if r is None:
        return None

    try:
        data = r.json()
        return data["market_data"]["current_price"]["usd"]
    except Exception:
        return None


def get_token_market_cap(symbol: str) -> Optional[float]:
    sym_up = symbol.upper()
    now = time.time()
    cached = MCAP_CACHE.get(sym_up)
    if cached and now - cached["ts"] < MCAP_TTL:
        return cached["mcap"]

    token_id = resolve_token_id(symbol)
    if not token_id:
        return None

    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "ids": token_id}
    r = safe_get(url, params=params)
    if r is None:
        return None

    try:
        data = r.json()
        if not data:
            return None
        mcap = data[0].get("market_cap")
    except Exception:
        return None

    if mcap is None:
        return None

    MCAP_CACHE[sym_up] = {"mcap": mcap, "ts": now}
    return mcap


# ===========================
# FORMATTING & DEGEN SCORE
# ===========================

def format_mcap(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    v = float(value)
    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.0f}"


def _mcap_risk_score(mcap: float) -> float:
    if mcap >= 10_000_000_000:
        return 1.0
    if mcap >= 1_000_000_000:
        return 3.0
    if mcap >= 200_000_000:
        return 5.0
    if mcap >= 50_000_000:
        return 7.0
    if mcap >= 5_000_000:
        return 8.0
    return 10.0


def _vol_risk_score(abs_change_24h: float) -> float:
    if abs_change_24h < 2:
        return 2.0
    if abs_change_24h < 5:
        return 4.0
    if abs_change_24h < 10:
        return 6.0
    if abs_change_24h < 20:
        return 8.0
    return 10.0


def degen_score(mcap: Optional[float], change_24h: Optional[float]) -> Optional[Dict[str, Any]]:
    if mcap is None:
        return None

    m_score = _mcap_risk_score(float(mcap))
    if change_24h is None:
        v_score = 6.0
    else:
        v_score = _vol_risk_score(abs(float(change_24h)))

    score = 0.6 * m_score + 0.4 * v_score
    score = max(1.0, min(10.0, score))

    if score <= 2.0:
        label = "Blue-chip 🪙 (low degen)"
    elif score <= 4.0:
        label = "Large-cap 💼"
    elif score <= 6.0:
        label = "Mid-cap ⚖️"
    elif score <= 8.0:
        label = "Microcap 🧪 (high degen)"
    else:
        label = "Meme / degen pit 🧨"

    return {"score": round(score, 1), "label": label}


# ===========================
# PNL CALC (WHATIFDATE ONLY)
# ===========================

def calc_what_if_date(symbol: str, usd_amount: float, date_str: str) -> Optional[Dict[str, Any]]:
    buy_price = get_historical_price_usd(symbol, date_str)
    if buy_price is None:
        return None

    current = get_current_price_usd(symbol)
    if current is None:
        return None

    tokens = usd_amount / buy_price
    current_value = tokens * current
    profit = current_value - usd_amount
    pct = (profit / usd_amount * 100) if usd_amount else 0

    return {
        "name": get_token_name(symbol) or symbol.upper(),
        "symbol": symbol.upper(),
        "usd_amount": usd_amount,
        "tokens": tokens,
        "buy_price": buy_price,
        "buy_date": date_str,
        "current_price": current,
        "initial_value": usd_amount,
        "current_value": current_value,
        "profit_abs": profit,
        "profit_pct": pct,
    }


# ===========================
# TELEGRAM COMMANDS
# ===========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "👋 *Welcome to the What-If Profit/Loss Bot!*\n\n"
        "Core commands:\n"
        "• `/whatifdate SYMBOL USD_AMOUNT YYYY-MM-DD`\n"
        "• `/addpos SYMBOL AMOUNT BUY_PRICE`\n"
        "• `/portfolio` – view all positions\n"
        "• `/ath SYMBOL` – all-time high info\n"
        "• `/clear` – clear your portfolio\n"
        "• `/remove SYMBOL` – remove one token\n\n"
        "Extra:\n"
        "• `/gm` – degen-style good morning\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def whatifdate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(
            "Usage: `/whatifdate SYMBOL USD_AMOUNT YYYY-MM-DD`\n"
            "Example: `/whatifdate SOL 1000 2023-01-01`",
            parse_mode="Markdown",
        )
        return

    symbol = args[0]
    try:
        usd_amount = float(args[1])
    except ValueError:
        await update.message.reply_text("USD amount must be a number.")
        return

    date_str = args[2]
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Date must be YYYY-MM-DD.")
        return

    res = calc_what_if_date(symbol, usd_amount, date_str)
    if res is None:
        await update.message.reply_text("Could not fetch historical/current price.")
        return

    mcap = get_token_market_cap(res["symbol"])
    d = degen_score(mcap, None)

    emoji = "🟢" if res["profit_abs"] > 0 else ("🔴" if res["profit_abs"] < 0 else "⚪️")

    text = (
        f"{emoji} *If you invested ${res['usd_amount']:,.2f} in {res['name']} on {res['buy_date']}:*\n\n"
        f"• Symbol: `{res['symbol']}`\n"
        f"• Buy price (that day): `${res['buy_price']:.4f}`\n"
        f"• Tokens bought: `{res['tokens']:.6f}`\n"
        f"• Current price: `${res['current_price']:.4f}`\n"
        f"• Market cap (now): `{format_mcap(mcap)}`\n"
    )
    if d:
        text += f"• Degen score: `{d['score']:.1f}/10` – {d['label']}\n"

    text += (
        "\n"
        f"• Initial value: `${res['initial_value']:,.2f}`\n"
        f"• Current value: `${res['current_value']:,.2f}`\n\n"
        f"• Profit/Loss: `${res['profit_abs']:,.2f}` ({res['profit_pct']:.2f}%)"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def addpos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(
            "Usage: `/addpos SYMBOL AMOUNT BUY_PRICE`\nExample: `/addpos SOL 10 80`",
            parse_mode="Markdown",
        )
        return

    symbol = args[0]
    try:
        amount = float(args[1])
        buy_price = float(args[2])
    except ValueError:
        await update.message.reply_text("Amount and buy price must be numbers.")
        return

    user = update.effective_user
    if not user:
        await update.message.reply_text("Could not get your user ID.")
        return

    add_user_position(user.id, symbol, amount, buy_price)
    await update.message.reply_text(
        f"Saved: {amount:g} {symbol.upper()} @ ${buy_price:.4f}\nUse `/portfolio` to view PnL.",
        parse_mode="Markdown",
    )


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show portfolio with more spacing / readability."""
    user = update.effective_user
    if not user:
        await update.message.reply_text("Could not get your user ID.")
        return

    positions = get_user_positions(user.id)
    if not positions:
        await update.message.reply_text(
            "You have no positions yet.\nAdd one with `/addpos SYMBOL AMOUNT BUY_PRICE`.",
            parse_mode="Markdown",
        )
        return

    total_initial = 0.0
    total_current = 0.0
    lines: List[str] = []

    for idx, pos in enumerate(positions, start=1):
        sym = pos["symbol"]
        amount = float(pos["amount"])
        buy_price = float(pos["buy_price"])

        current_price = get_current_price_usd(sym)
        if current_price is None:
            continue

        initial_value = amount * buy_price
        current_value = amount * current_price
        profit_abs = current_value - initial_value
        profit_pct = (profit_abs / initial_value * 100) if initial_value != 0 else 0

        total_initial += initial_value
        total_current += current_value

        emoji = "🟢" if profit_abs > 0 else ("🔴" if profit_abs < 0 else "⚪️")

        # Extra spacing + clearer layout
        line = (
            f"{idx}. {emoji} *{sym}*\n"
            f"   • Amount: `{amount:g}`\n"
            f"   • Buy price: `${buy_price:.4f}`\n"
            f"   • Current price: `${current_price:.4f}`\n"
            f"   • Value: `${current_value:,.2f}`\n"
            f"   • PnL: `${profit_abs:,.2f}` ({profit_pct:.2f}%)"
        )
        lines.append(line)

    total_profit = total_current - total_initial
    total_pct = (total_profit / total_initial * 100) if total_initial != 0 else 0
    emoji = "🟢" if total_profit > 0 else ("🔴" if total_profit < 0 else "⚪️")

    header = (
        f"{emoji} *Portfolio Summary*\n\n"
        f"• Initial: `${total_initial:,.2f}`\n"
        f"• Current: `${total_current:,.2f}`\n"
        f"• PnL: `${total_profit:,.2f}` ({total_pct:.2f}%)\n\n"
        "*Positions:*\n\n"
    )

    # Join with a blank line between each position
    body = "\n\n".join(lines)
    await update.message.reply_text(header + body, parse_mode="Markdown")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        await update.message.reply_text("Could not get your user ID.")
        return

    all_data = load_all_positions()
    key = str(user.id)

    if key in all_data and all_data[key]:
        all_data[key] = []
        save_all_positions(all_data)
        await update.message.reply_text("🗑️ Your entire portfolio has been cleared.")
    else:
        await update.message.reply_text("You don't have any saved positions yet.")


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "Usage: `/remove SYMBOL`\nExample: `/remove SOL`",
            parse_mode="Markdown",
        )
        return

    symbol = args[0].upper()
    user = update.effective_user
    if not user:
        await update.message.reply_text("Could not get your user ID.")
        return

    all_data = load_all_positions()
    key = str(user.id)
    positions = all_data.get(key, [])

    new_positions = [p for p in positions if p.get("symbol") != symbol]

    if len(new_positions) == len(positions):
        await update.message.reply_text(
            f"No `{symbol}` positions found in your portfolio.",
            parse_mode="Markdown",
        )
        return

    all_data[key] = new_positions
    save_all_positions(all_data)

    await update.message.reply_text(
        f"🗑️ Removed all `{symbol}` positions from your portfolio.",
        parse_mode="Markdown",
    )


async def ath(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "Usage: `/ath SYMBOL`\nExample: `/ath SOL`",
            parse_mode="Markdown",
        )
        return

    symbol = args[0]
    token_id = resolve_token_id(symbol)
    if not token_id:
        await update.message.reply_text("Could not resolve that token symbol.")
        return

    url = f"https://api.coingecko.com/api/v3/coins/{token_id}"
    r = safe_get(url, params={"localization": "false"})
    if r is None:
        await update.message.reply_text("Could not fetch ATH info.")
        return

    try:
        data = r.json()
        name = data.get("name", symbol.upper())
        md = data["market_data"]
        ath_price = md["ath"]["usd"]
        ath_date_iso = md["ath_date"]["usd"]
        current_price = md["current_price"]["usd"]
        mcap = md["market_cap"]["usd"]
        change_24h = md.get("price_change_percentage_24h")
    except Exception:
        await update.message.reply_text("ATH data not available for this token.")
        return

    # Format date nicely
    try:
        dt = datetime.fromisoformat(ath_date_iso.replace("Z", "+00:00"))
        ath_date_str = dt.date().isoformat()
    except Exception:
        ath_date_str = ath_date_iso

    if ath_price and ath_price > 0:
        diff_pct = (current_price / ath_price - 1) * 100
    else:
        diff_pct = 0.0

    d = degen_score(mcap, change_24h)

    text = (
        f"📈 *All-Time High for {name} ({symbol.upper()})*\n\n"
        f"• ATH price: `${ath_price:,.4f}`\n"
        f"• ATH date: `{ath_date_str}`\n"
        f"• Current price: `${current_price:,.4f}`\n"
        f"• Market cap: `{format_mcap(mcap)}`\n"
    )

    if diff_pct < 0:
        text += f"• Currently `{-diff_pct:.2f}%` below ATH\n"
    elif diff_pct > 0:
        text += f"• Currently `{diff_pct:.2f}%` ABOVE ATH 🤯\n"

    if d:
        text += f"• Degen score: `{d['score']:.1f}/10` – {d['label']}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def gm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msgs = [
        "gm anon ☀️",
        "gm, may your bags be green today 🟢",
        "gm, remember: time in the market > timing the market.",
        "gm, stay hydrated and avoid 50x leverage.",
    ]
    await update.message.reply_text(random.choice(msgs))


# ===========================
# MAIN
# ===========================

def main() -> None:
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError("Please set your Telegram bot token in BOT_TOKEN or env var BOT_TOKEN.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whatifdate", whatifdate))
    app.add_handler(CommandHandler("addpos", addpos))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("ath", ath))
    app.add_handler(CommandHandler("gm", gm))

    logger.info("What-If Profit/Loss Bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
