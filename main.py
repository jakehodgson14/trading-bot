import os
import json
import base64
import threading
import time
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot
import finnhub
from flask import Flask, request

# ========= CONFIG =========
SCAN_INTERVAL_SECONDS = 15 * 60     # background watchlist scan every 15 minutes
WATCH_SHEET_NAME = "Watchlist"      # sheet tab name (unused for /best)
MIN_SURGE_TIERS = [15, 20, 30]      # watchlist alert tiers

# Weekly “Best Trades”
BEST_UNIVERSE = "SP500"             # target universe (SP500) with fallback to mega-caps
BEST_TOP_N = 10                     # how many symbols to send
BEST_RUN_DAY = 0                    # Monday=0 ... Sunday=6 (Europe/London)
BEST_RUN_HOUR = 9                   # 09:00 Europe/London
BEST_MIN_PRICE = 5.0                # filter out penny stocks
BEST_MIN_AVG_VOL = 1_000_000        # 5-day avg volume filter

# ==========================

# ======== ENV ========
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
sheet_id = os.getenv("SHEET_ID")
telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_id = os.getenv("TELEGRAM_ID")
render_url = os.getenv("RENDER_EXTERNAL_URL")
finnhub_key = os.getenv("FINNHUB_KEY")

if not all([creds_b64, sheet_id, telegram_token, telegram_id, render_url, finnhub_key]):
    raise RuntimeError("Missing one or more environment variables: GOOGLE_CREDENTIALS_B64, SHEET_ID, TELEGRAM_TOKEN, TELEGRAM_ID, RENDER_EXTERNAL_URL, FINNHUB_KEY")

# ===== Google Auth =====
creds_json = base64.b64decode(creds_b64).decode("utf-8")
creds_dict = json.loads(creds_json)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
gc = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope))

# Open spreadsheet and worksheet (still used by other commands)
ss = gc.open_by_key(sheet_id)
try:
    ws = ss.worksheet(WATCH_SHEET_NAME)
except Exception:
    ws = ss.get_worksheet(0)

# ===== Telegram Bot =====
bot = telebot.TeleBot(telegram_token)
app = Flask(__name__)

# ===== Finnhub Client =====
finnhub_client = finnhub.Client(api_key=finnhub_key)

# ===== Helpers =====
def safe_float(x) -> float:
    try:
        if x is None or x == "":
            return float("nan")
        return float(str(x).replace(",", "").strip())
    except Exception:
        return float("nan")

def load_watchlist() -> List[Dict[str, Any]]:
    try:
        records = ws.get_all_records()
    except Exception:
        return []
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

def format_money(x: float) -> str:
    if x != x:
        return "—"
    return f"{x:,.2f}"

def format_pct(x: float) -> str:
    if x != x:
        return "—"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"

# ====== Price (Finnhub) for regular commands ======
def fetch_quote(ticker: str) -> Dict[str, Any]:
    try:
        q = finnhub_client.quote(ticker)
        price = q.get("c", float("nan"))
        prev_close = q.get("pc", float("nan"))
        change_pct = ((price - prev_close) / prev_close * 100.0) if prev_close and prev_close == prev_close else float("nan")
        return {"ticker": ticker, "price": price, "prev_close": prev_close, "change_pct_1d": change_pct}
    except Exception as e:
        return {"ticker": ticker, "price": float("nan"), "prev_close": float("nan"),
                "change_pct_1d": float("nan"), "error": str(e)}

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

# ===== Background scan (watchlist alerts) =====
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

# ===== Market-wide “Best Trades” =====
_MEGA_CAP_FALLBACK = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","BRK.B",
    "LLY","JPM","WMT","UNH","XOM","JNJ","PG","MA","HD","COST","ORCL","MRK","PEP","BAC",
    "KO","ABBV","NFLX","CRM","LIN","V","ADBE"
]

def get_universe() -> List[str]:
    """Try S&P500 via Finnhub; fallback to mega-caps if unavailable."""
    if BEST_UNIVERSE.upper() == "SP500":
        try:
            data = finnhub_client.indices_constituents("^GSPC")
            syms = data.get("constituents", [])
            if syms:
                return [s for s in syms if isinstance(s, str)]
        except Exception:
            pass
    return _MEGA_CAP_FALLBACK

def _candles(symbol: str, fro: int, to: int) -> Dict[str, Any]:
    # Daily candles; Finnhub returns dict with 'c','h','l','o','t','v','s'
    return finnhub_client.stock_candles(symbol, "D", fro, to)

def _week_perf_and_quality(symbol: str, now_utc: datetime) -> Tuple[float, float, float, float]:
    """
    Returns (week_pct, last_close, avg_vol_5, atr5_approx)
    atr5_approx ~= avg(high-low) over last 5 closes.
    """
    to_ts = int(now_utc.timestamp())
    fro_ts = int((now_utc - timedelta(days=15)).timestamp())  # enough bars to cover 7 trading days
    data = _candles(symbol, fro_ts, to_ts)
    if not data or data.get("s") != "ok" or len(data.get("c", [])) < 6:
        return float("nan"), float("nan"), float("nan"), float("nan")
    closes = data["c"]
    highs = data["h"]
    lows = data["l"]
    vols = data["v"]

    last_close = float(closes[-1])
    prev_index = max(0, len(closes) - 6)  # ~1 calendar week back (5 bars diff)
    prev_close = float(closes[prev_index])
    week_pct = ((last_close - prev_close) / prev_close * 100.0) if prev_close else float("nan")

    # 5-day averages
    n5 = min(5, len(vols))
    avg_vol_5 = float(sum(vols[-n5:]) / n5)
    atr5 = sum((h - l) for h, l in zip(highs[-n5:], lows[-n5:])) / n5 if n5 > 0 else float("nan")

    return week_pct, last_close, avg_vol_5, atr5

def compute_best_trades(top_n: int = BEST_TOP_N) -> List[Dict[str, Any]]:
    now_utc = datetime.now(timezone.utc)
    universe = get_universe()[:200]  # cap to avoid rate issues
    picks = []
    for i, sym in enumerate(universe):
        # keep within free rate limits
        if i and i % 50 == 0:
            time.sleep(1.2)
        try:
            week_pct, last_close, avg_vol_5, atr5 = _week_perf_and_quality(sym, now_utc)
            if last_close == last_close and last_close >= BEST_MIN_PRICE and \
               avg_vol_5 == avg_vol_5 and avg_vol_5 >= BEST_MIN_AVG_VOL and \
               week_pct == week_pct and week_pct > 0:
                picks.append({
                    "symbol": sym,
                    "week_pct": week_pct,
                    "last": last_close,
                    "avg_vol_5": avg_vol_5,
                    "atr5": atr5
                })
        except Exception:
            continue

    picks.sort(key=lambda x: x["week_pct"], reverse=True)
    return picks[:top_n]

def format_best_trades(picks: List[Dict[str, Any]]) -> str:
    if not picks:
        return "😕 No qualifying symbols this week (filters too strict or market broadly down)."
    lines = ["📈 Best Trades – Top momentum (1-week):"]
    for p in picks:
        lines.append(
            f"• {p['symbol']}: {format_pct(p['week_pct'])} | Px {format_money(p['last'])} | "
            f"ATR(5)~{format_money(p['atr5'])} | AvgVol5 {int(p['avg_vol_5']):,}"
        )
    lines.append("\nFilters: price ≥ $5, avg vol(5) ≥ 1M, positive 1-week perf.")
    return "\n".join(lines)

def weekly_best_trades_worker():
    """Run every minute; send once at Monday 09:00 Europe/London."""
    sent_for_week = None
    tz = ZoneInfo("Europe/London")
    while True:
        try:
            now = datetime.now(tz)
            week_tag = f"{now.isocalendar().year}-W{now.isocalendar().week}"
            if now.weekday() == BEST_RUN_DAY and now.hour == BEST_RUN_HOUR and \
               (sent_for_week != week_tag):
                picks = compute_best_trades(BEST_TOP_N)
                bot.send_message(chat_id=telegram_id, text=format_best_trades(picks))
                sent_for_week = week_tag
        except Exception as e:
            try:
                bot.send_message(chat_id=telegram_id, text=f"❌ Weekly screen error: {e}")
            except Exception:
                pass
        time.sleep(60)

# ===== Commands =====
@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.reply_to(message,
        "📖 Commands:\n"
        "/status – bot + sheet health\n"
        "/tickers – list watchlist tickers\n"
        "/price TICKER – live price (stocks/crypto via Finnhub)\n"
        "/rows – number of rows in watchlist\n"
        "/report – snapshot P/L (sheet watchlist)\n"
        "/watch – re-read sheet now\n"
        "/best – market-wide weekly momentum picks (top)\n"
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
        bot.reply_to(message, "Usage: /price TICKER\nExamples: /price TSLA, /price AAPL, /price BTCUSDT (use exchange prefix if needed)")
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

@bot.message_handler(commands=['best'])
def cmd_best(message):
    bot.reply_to(message, "🔎 Screening the market for top 1-week momentum…")
    try:
        picks = compute_best_trades(BEST_TOP_N)
        bot.reply_to(message, format_best_trades(picks))
    except Exception as e:
        bot.reply_to(message, f"❌ Best-trades error: {e}")

# ===== Flask Webhook =====
@app.route(f"/{telegram_token}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok", 200

# ===== Healthcheck =====
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if __name__ == "__main__":
    # Build webhook URL
    clean_url = render_url.replace("https://", "").replace("http://", "").strip("/")
    webhook_url = f"https://{clean_url}/{telegram_token}"
    print("🚀 Setting webhook to:", webhook_url)

    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)

    # Kick off background processes
    threading.Timer(2.0, background_scan).start()
    threading.Thread(target=weekly_best_trades_worker, daemon=True).start()

    print("🤖 Bot running with webhooks…")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
