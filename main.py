import os
import json
import base64
from typing import List, Dict, Any

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot
import yfinance as yf

# ========= CONFIG =========
WATCH_SHEET_NAME = "Watchlist"    # tab name with your tickers
# ==========================

# ======== ENV ========
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
sheet_id = os.getenv("SHEET_ID")
telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_id = os.getenv("TELEGRAM_ID")

if not all([creds_b64, sheet_id, telegram_token, telegram_id]):
    raise RuntimeError("Missing one or more environment variables.")

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
            "Note": row.get("Note", "")
        })
    return out

def fetch_quote(ticker: str) -> Dict[str, Any]:
    t = yf.Ticker(ticker)
    try:
        hist = t.history(period="2d", interval="1d")
        price = float(hist["Close"].iloc[-1]) if not hist.empty else float("nan")
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else float("nan")

        change_pct_1d = float("nan")
        if (price == price) and (prev_close == prev_close) and prev_close != 0:
            change_pct_1d = (price - prev_close) / prev_close * 100.0

        return {"ticker": ticker, "price": price, "change_pct_1d": change_pct_1d}
    except Exception:
        return {"ticker": ticker, "price": float("nan"), "change_pct_1d": float("nan")}

def format_money(x: float) -> str:
    return "—" if x != x else f"{x:,.2f}"

def format_pct(x: float) -> str:
    return "—" if x != x else f"{x:+.2f}%"

# ===== Commands =====
@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.reply_to(message,
        "📖 Commands:\n"
        "/status – bot + sheet health\n"
        "/tickers – list watchlist tickers\n"
        "/price TICKER – live price (e.g. /price AAPL)\n"
        "/rows – number of rows in watchlist\n"
        "/report – snapshot prices\n"
    )

@bot.message_handler(commands=['status'])
def cmd_status(message):
    try:
        title = ss.title
        bot.reply_to(message, f"✅ Bot OK. Sheet: {title}")
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
    bot.reply_to(message, f"{ticker}: {format_money(q['price'])} | 1D {format_pct(q['change_pct_1d'])}")

@bot.message_handler(commands=['rows'])
def cmd_rows(message):
    try:
        cnt = len(ws.get_all_values())
        bot.reply_to(message, f"Rows incl header: {cnt}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['report'])
def cmd_report(message):
    wl = load_watchlist()
    if not wl:
        bot.reply_to(message, "No tickers to report.")
        return
    lines = ["📊 Report:"]
    for row in wl[:25]:
        q = fetch_quote(row["Ticker"])
        lines.append(f"• {row['Ticker']}: {format_money(q['price'])} ({format_pct(q['change_pct_1d'])})")
    bot.reply_to(message, "\n".join(lines))

# ===== Startup =====
bot.send_message(chat_id=telegram_id, text="✅ Lite Copilot online. Use /help for commands.")
print("🤖 Running Lite Cockpit…")
bot.infinity_polling(timeout=30, long_polling_timeout=30)
