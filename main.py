import os
import json
import time
import base64
import threading
from typing import List, Dict, Any

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot
import yfinance as yf

# ========= CONFIG =========
SCAN_INTERVAL_SECONDS = 15 * 60   # background scan every 15 minutes
WATCH_SHEET_NAME = "Watchlist"    # tab name with your tickers (first row = headers as documented)
MIN_SURGE_TIERS = [15, 20, 30]    # % surge tiers for alerts (24h change)
# ==========================

# ======== ENV ========
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
sheet_id = os.getenv("SHEET_ID")
telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_id = os.getenv("TELEGRAM_ID")

if not all([creds_b64, sheet_id, telegram_token, telegram_id]):
    raise RuntimeError("Missing one or more environment variables: GOOGLE_CREDENTIALS_B64, SHEET_ID, TELEGRAM_TOKEN, TELEGRAM_ID")

# ===== Google Auth =====
creds_json = base64.b64decode(creds_b64).decode("utf-8")
creds_dict = json.loads(creds_json)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
gc = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope))

# Open spreadsheet and worksheet
ss = gc.open_by_key(sheet_id)
try:
    ws = ss.worksheet(WATCH_SHEET_NAME)
except Exception:
    ws = ss.get_worksheet(0)

# ===== Telegram Bot =====
bot = telebot.TeleBot(telegram_token)

def safe_float(x) -> float:
    try:
        if x is None or x == "":
            return float("nan")
        return float(str(x).replace(",", "").strip())
    except Exception:
        return float("nan")

def load_watchlist() -> List[Dict[str, Any]]:
    records = ws.get_all_records()
    out = []
    for row in records:
        ticker = str(row.get("Ticker", "")).strip().upper()
        if not ticker:
            continue
        out.append({
            "Ticker": ticker,
            "Shares": safe_float(row.get("Shares")),
            "Entry": safe_float(row.get("Entry")),
            "FloorValue": safe_float(row.get("FloorValue")),
            "FloorThresholdPct": safe_float(row.get("FloorThresholdPct")),
            "Note": row.get("Note", "")
        })
    return out

def fetch_quote(ticker: str) -> Dict[str, Any]:
    """
    Returns dict with price info using yfinance:
    { 'ticker', 'price', 'prev_close', 'change_pct_1d' }
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", interval="1d")
        if hist.empty:
            return {"ticker": ticker, "price": float("nan"),
                    "prev_close": float("nan"), "change_pct_1d": float("nan")}

        price = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else float("nan")

        change_pct_1d = (price - prev_close) / prev_close * 100.0 if prev_close and prev_close == prev_close else float("nan")

        return {"ticker": ticker, "price": price, "prev_close": prev_close, "change_pct_1d": change_pct_1d}
    except Exception as e:
        return {"ticker": ticker, "price": float("nan"),
                "prev_close": float("nan"), "change_pct_1d": float("nan"),
                "error": str(e)}

def format_money(x: float) -> str:
    if x != x:  # NaN
        return "—"
    return f"{x:,.2f}"

def format_pct(x: float) -> str:
    if x != x:
        return "—"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"

def calc_pl(shares: float, entry: float, price: float) -> Dict[str, Any]:
    if not (shares == shares and entry == entry and price == price):
        return {"invested": float("nan"), "current_value": float("nan"), "pl_abs": float("nan"), "pl_pct": float("nan")}
    invested = shares * entry
    current_value = shares * price
    pl_abs = current_value - invested
    pl_pct = (pl_abs / invested * 100.0) if invested else float("nan")
    return {"invested": invested, "current_value": current_value, "pl_abs": pl_abs, "pl_pct": pl_pct}

def should_alert_surges(change_pct: float, tiers=MIN_SURGE_TIERS) -> List[int]:
    if change_pct != change_pct:
        return []
    return [t for t in sorted(tiers) if abs(change_pct) >= t]

def check_floor_breach(invested: float, current_value: float, floor_value: float, floor_threshold_pct: float) -> str:
    if invested == invested and current_value == current_value:
        if floor_value == floor_value and current_value <= floor_value:
            return "floor_value"
        if floor_threshold_pct == floor_threshold_pct and floor_threshold_pct > 0:
            loss_pct = ((invested - current_value) / invested * 100.0) if invested else float("nan")
            if loss_pct == loss_pct and loss_pct >= floor_threshold_pct:
                return "threshold_pct"
    return ""

def build_status_line(q: Dict[str, Any], pl: Dict[str, Any]) -> str:
    return (
        f"{q['ticker']}: Px {format_money(q['price'])} | 1D {format_pct(q['change_pct_1d'])} | "
        f"Inv {format_money(pl['invested'])} → Val {format_money(pl['current_value'])} "
        f"({format_money(pl['pl_abs'])}, {format_pct(pl['pl_pct'])})"
    )

def background_scan():
    try:
        wl = load_watchlist()
        if not wl:
            threading.Timer(SCAN_INTERVAL_SECONDS, background_scan).start()
            return

        for row in wl:
            ticker = row["Ticker"]
            q = fetch_quote(ticker)
            shares, entry = row["Shares"], row["Entry"]
            floor_value, floor_pct = row["FloorValue"], row["FloorThresholdPct"]

            pl = calc_pl(shares, entry, q["price"])

            tiers_hit = should_alert_surges(q["change_pct_1d"])
            if tiers_hit:
                dir_emoji = "🟢" if q["change_pct_1d"] >= 0 else "🔴"
                bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        f"🔥 Surge Alert {dir_emoji}\n"
                        f"Ticker: {ticker}\n"
                        f"1D Change: {format_pct(q['change_pct_1d'])}\n"
                        f"Price: {format_money(q['price'])}\n"
                        f"Tiers hit: {', '.join([str(t)+'%' for t in tiers_hit])}\n"
                        f"P/L: {format_money(pl['pl_abs'])} ({format_pct(pl['pl_pct'])})"
                    )
                )

            reason = check_floor_breach(pl["invested"], pl["current_value"], floor_value, floor_pct)
            if reason:
                reason_text = "fell below FloorValue" if reason == "floor_value" else f"loss ≥ {int(floor_pct)}%"
                bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        f"⚠️ Reassess Alert 🔻\n"
                        f"{ticker} {reason_text}\n"
                        f"Invested: {format_money(pl['invested'])}\n"
                        f"Current: {format_money(pl['current_value'])}\n"
                        f"P/L: {format_money(pl['pl_abs'])} ({format_pct(pl['pl_pct'])})"
                    )
                )

        threading.Timer(SCAN_INTERVAL_SECONDS, background_scan).start()

    except Exception as e:
        bot.send_message(chat_id=telegram_id, text=f"❌ Scan error: {e}")
        threading.Timer(SCAN_INTERVAL_SECONDS, background_scan).start()

# ===== Commands =====
@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.reply_to(message,
        "📖 Commands:\n"
        "/status – bot + sheet health\n"
        "/tickers – list watchlist tickers\n"
        "/price TICKER – live price (e.g. /price AAPL)\n"
        "/rows – number of rows in watchlist\n"
        "/report – snapshot P/L & moves\n"
        "/watch – re-read sheet now"
    )

@bot.message_handler(commands=['status'])
def cmd_status(message):
    try:
        title = ss.title
        bot.reply_to(message, f"✅ Bot OK. Sheet: {title}. Scan interval: {SCAN_INTERVAL_SECONDS//60}m")
    except Exception as e:
        bot.reply_to(message, f"❌ Status error: {e}")

@bot.message_handler(commands=['tickers'])
def cmd_tickers(message):
    wl = load_watchlist()
    if not wl:
        bot.reply_to(message, "No tickers found in Watchlist.")
        return
    tlist = ", ".join([r['Ticker'] for r in wl])
    bot.reply_to(message, f"📋 Watchlist: {tlist}")

@bot.message_handler(commands=['price'])
def cmd_price(message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /price TICKER")
        return
    ticker = parts[1].upper()
    q = fetch_quote(ticker)
    if "error" in q:
        bot.reply_to(message, f"{ticker}: Error fetching data ({q['error']})")
    else:
        bot.reply_to(message, f"{ticker}: {format_money(q['price'])} | 1D {format_pct(q['change_pct_1d'])}")

@bot.message_handler(commands=['rows'])
def cmd_rows(message):
    try:
        cnt = len(ws.get_all_values())
        bot.reply_to(message, f"Rows incl header: {cnt}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['watch'])
def cmd_watch(message):
    bot.reply_to(message, "🔄 Reloading sheet and scanning now…")
    threading.Thread(target=background_scan, daemon=True).start()

@bot.message_handler(commands=['report'])
def cmd_report(message):
    wl = load_watchlist()
    if not wl:
        bot.reply_to(message, "No tickers to report.")
        return
    lines = ["📊 Report:"]
    for row in wl[:25]:
        q = fetch_quote(row["Ticker"])
        pl = calc_pl(row["Shares"], row["Entry"], q["price"])
        lines.append("• " + build_status_line(q, pl))
    bot.reply_to(message, "\n".join(lines))

# ===== Startup =====
bot.send_message(chat_id=telegram_id, text="✅ Copilot Cockpit online. Use /help for commands.")
threading.Timer(2.0, background_scan).start()

print("🤖 Running…")
bot.infinity_polling(timeout=30, long_polling_timeout=30)
