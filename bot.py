import yfinance as yf
import pandas as pd
import requests
import datetime
import json
import os

# ==============================================
#   Engineer Wealth Bot V3.0
#   Features:
#   - Market Mood (Fear & Greed)
#   - Tactical Dashboard (RSI + Signal)
#   - Trend Analysis + % ห่างจาก MA120
#   - Volume Spike Detection
#   - DXY (Dollar Index)
#   - Alert เฉพาะเมื่อ Signal เปลี่ยน
#   - Weekly Summary (วันศุกร์)
# ==============================================

DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')
STATE_FILE          = "signal_state.json"

PORT_TICKERS  = ['QQQM', 'SMH']
TREND_TICKERS = ['^NDX', 'QQQM', 'SMH', 'DX-Y.NYB']  # เพิ่ม DXY

# --- HELPER: RSI ---
def calculate_rsi(series, period=14):
    delta    = series.diff()
    gain     = (delta.where(delta > 0, 0)).fillna(0)
    loss     = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs       = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# --- HELPER: Fear & Greed ---
def get_market_mood():
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        r   = requests.get(url, timeout=10)
        data = r.json()
        score  = int(data['data'][0]['value'])
        rating = data['data'][0]['value_classification']
        return score, rating
    except:
        return None, None

# --- HELPER: Signal State ---
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# --- HELPER: Discord ---
def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL: return
    data = {
        "content":    content[:2000],
        "username":   "Engineer Wealth Bot V3.0",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2554/2554037.png"
    }
    requests.post(DISCORD_WEBHOOK_URL, json=data)

# ==============================================
#   MAIN
# ==============================================
def get_portfolio_dashboard():
    thai_now  = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    date_str  = thai_now.strftime('%Y-%m-%d')
    is_friday = thai_now.weekday() == 4

    print(f"🔄 Running... {date_str} (Friday={is_friday})")

    # --- Market Mood ---
    mood_score, mood_rating = get_market_mood()
    mood_text = "N/A"
    if mood_score is not None:
        if mood_score < 25:   emoji = "😨"
        elif mood_score < 45: emoji = "😰"
        elif mood_score > 75: emoji = "🤑"
        elif mood_score > 55: emoji = "😏"
        else:                 emoji = "😐"
        mood_text = f"`{mood_score}/100` {emoji} {mood_rating}"

    # --- Load signal state ---
    prev_state     = load_state()
    new_state      = {}
    signal_changed = False

    tactical_rows = []
    trend_rows    = []
    volume_alerts = []
    weekly_rows   = []

    for ticker in TREND_TICKERS:
        try:
            stock = yf.Ticker(ticker)
            df    = stock.history(period="2y")
            if df.empty: continue

            current_price = df['Close'].iloc[-1]
            ma120 = df['Close'].rolling(window=120).mean().iloc[-1]
            ma250 = df['Close'].rolling(window=250).mean().iloc[-1]

            # Display name
            if ticker == '^NDX':       display_name = "NDX100"
            elif ticker == 'DX-Y.NYB': display_name = "DXY"
            else:                      display_name = ticker

            # --- TREND + % ห่างจาก MA120 ---
            is_uptrend = current_price > ma120 if not pd.isna(ma120) else False
            trend_icon = "🟢" if is_uptrend else "🔴"
            ma120_str  = f"{ma120:.2f}" if not pd.isna(ma120) else "-"
            ma250_str  = f"{ma250:.2f}" if not pd.isna(ma250) else "-"

            if not pd.isna(ma120):
                pct_from_ma = ((current_price - ma120) / ma120) * 100
                pct_str     = f"{pct_from_ma:+.1f}%"
            else:
                pct_str = "-"

            trend_rows.append(
                f"{trend_icon} {display_name:<6} {current_price:>8.2f} {ma120_str:>9} {ma250_str:>9}  {pct_str}"
            )

            # --- VOLUME SPIKE ---
            if 'Volume' in df.columns and len(df) >= 21:
                vol_today = df['Volume'].iloc[-1]
                vol_avg20 = df['Volume'].iloc[-21:-1].mean()
                if vol_avg20 > 0 and vol_today > vol_avg20 * 1.5:
                    spike_x = vol_today / vol_avg20
                    volume_alerts.append(
                        f"⚡ **{display_name}** Volume spike `{spike_x:.1f}x` avg"
                    )

            # --- TACTICAL + SIGNAL CHANGE ---
            if ticker in PORT_TICKERS:
                rsi        = calculate_rsi(df['Close']).iloc[-1]
                prev_price = df['Close'].iloc[-2]
                change_pct = ((current_price - prev_price) / prev_price) * 100

                signal, icon = "HOLD", "➖"
                if rsi < 35:                       signal, icon = "BUY",   "🔥"
                elif rsi < 45 and ticker == 'SMH': signal, icon = "WATCH", "👀"
                elif rsi > 70:                     signal, icon = "WAIT",  "⚠️"

                # ตรวจว่า signal เปลี่ยนจากรอบก่อนไหม
                prev_signal = prev_state.get(ticker, {}).get('signal', None)
                new_state[ticker] = {'signal': signal, 'rsi': round(rsi, 1)}
                if prev_signal and prev_signal != signal:
                    signal_changed = True
                    signal = f"{prev_signal}→{signal}"  # แสดงการเปลี่ยน

                tactical_rows.append(
                    f"{ticker:<6} {current_price:>8.2f} {change_pct:>7.1f}% {rsi:>4.0f}  {icon} {signal}"
                )

                # Weekly Summary
                if is_friday:
                    prev_rsi   = prev_state.get(ticker, {}).get('rsi', None)
                    rsi_change = f"{rsi - prev_rsi:+.1f}" if prev_rsi else "N/A"
                    weekly_rows.append(
                        f"{ticker:<6} RSI {rsi:.0f} ({rsi_change} จากรอบก่อน)  {icon} {signal}"
                    )

        except Exception as e:
            print(f"❌ Error {ticker}: {e}")

    # --- Save new state ---
    save_state(new_state)

    # ==============================================
    #   BUILD MESSAGE
    # ==============================================
    msg  = f"🤖 **ENGINEER WEALTH BOT V3.0**\n"
    msg += f"📅 {date_str} (Asia/Bangkok)\n"
    msg += f"🌡️ **Market Mood:** {mood_text}\n\n"

    # Table 1: Tactical Dashboard
    msg += "**📊 Tactical Dashboard**\n```\n"
    msg += f"{'Asset':<6} {'Price':>8} {'%Chg':>8} {'RSI':>4}  Signal\n"
    msg += "-" * 42 + "\n"
    for row in tactical_rows:
        msg += row + "\n"
    msg += "```\n"

    # Table 2: Trend Analysis
    msg += "**📉 Trend Analysis**\n```\n"
    msg += f"{'Asset':<6} {'Price':>8} {'MA120':>9} {'MA250':>9}  vs MA120\n"
    msg += "-" * 48 + "\n"
    for row in trend_rows:
        msg += row + "\n"
    msg += "```\n"

    # Volume Spike
    if volume_alerts:
        msg += "**📦 Volume Spike**\n"
        for alert in volume_alerts:
            msg += alert + "\n"
        msg += "\n"

    # Weekly Summary (วันศุกร์เท่านั้น)
    if is_friday and weekly_rows:
        msg += "**📆 Weekly Summary**\n```\n"
        for row in weekly_rows:
            msg += row + "\n"
        msg += "```\n"

    send_discord_alert(msg)
    print("✅ Sent!" if DISCORD_WEBHOOK_URL else "⚠️ No webhook set")

if __name__ == "__main__":
    get_portfolio_dashboard()
