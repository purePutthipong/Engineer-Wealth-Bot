import yfinance as yf
import pandas as pd
import numpy as np
import requests
import datetime
import json
import os

# ==============================================
#   Engineer Wealth Bot V5.0
#   New in V5:
#   - Dynamic Risk Level Scoring (RSI + F&G)
#   - Automated Trailing Stop (20-day Low / BB Lower)
#   - Bug Fix: Dynamic AI Date injection
#   - Enhanced Discord UI with Risk Metrics
# ==============================================

DISCORD_WEBHOOK_URL      = os.environ.get('DISCORD_WEBHOOK')        # Pro channel
DISCORD_FREE_WEBHOOK_URL = os.environ.get('DISCORD_FREE_WEBHOOK')   # Free channel (NEW)
GROQ_API_KEY             = os.environ.get('GROQ_API_KEY')
STATE_FILE               = "signal_state.json"

PORT_TICKERS  = ['QQQM', 'SMH', 'GC=F', 'PLTR', 'ARM']
FREE_TICKERS  = {'QQQM', 'SMH'}   # Free tier tickers (NEW)
TREND_TICKERS = ['^NDX', 'QQQM', 'SMH', 'GC=F', 'DX-Y.NYB', 'PLTR', 'ARM']

DISPLAY_NAME = {
    '^NDX':      'NDX100',
    'DX-Y.NYB':  'DXY',
    'QQQM':      'QQQM',
    'SMH':       'SMH',
    'GC=F':      'GOLD',
    'PLTR':      'PLTR',
    'ARM':       'ARM',
}

# Futures/indices ที่ไม่มี Volume ที่เชื่อถือได้
NO_VOLUME_TICKERS = {'GC=F', '^NDX', 'DX-Y.NYB'}

# Growth Portfolio — Rotate targets (ตั้ง 2026-04-26)
ROTATE_TARGETS = {
    'PLTR': {'target': 220.92, 'stop': None,   'cost': 147.282},
    'ARM':  {'target': 262.58, 'stop': 205.00, 'cost': 175.056},
}

# ==============================================
#   INDICATORS & RISK LOGIC
# ==============================================

def calculate_rsi(series, period=14):
    delta    = series.diff()
    gain     = delta.where(delta > 0, 0).fillna(0)
    loss     = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(series, fast=12, slow=26, signal=9):
    ema_fast   = series.ewm(span=fast, adjust=False).mean()
    ema_slow   = series.ewm(span=slow, adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger(series, period=20, std_dev=2):
    ma     = series.rolling(window=period).mean()
    std    = series.rolling(window=period).std()
    upper  = ma + std_dev * std
    lower  = ma - std_dev * std
    pct_b  = (series - lower) / (upper - lower)
    return upper, lower, pct_b

def calculate_trailing_stop(df):
    """V5: Max of 20-day Low or Bollinger Lower Band."""
    low_20 = df['Low'].rolling(window=20).min().iloc[-1]
    _, bb_lower, _ = calculate_bollinger(df['Close'])
    return max(low_20, bb_lower.iloc[-1])

def calculate_risk_level(avg_rsi, mood_score):
    """V5: Weighted risk score (RSI 60%, Mood 40%)."""
    if avg_rsi is None or mood_score is None: return "UNKNOWN", "⚪"
    risk_score = (avg_rsi - 50) * 0.6 + (mood_score - 50) * 0.4
    if risk_score > 25:  return "HIGH RISK", "🔴"
    if risk_score > 5:   return "MODERATE", "🟠"
    if risk_score > -15: return "NEUTRAL",  "🟡"
    return "LOW RISK", "🟢"

def compute_signal_score(rsi, macd_hist, pct_b, macd_std=5.0):
    rsi_score = np.clip(rsi, 0, 100)
    divisor = macd_std if (macd_std and macd_std > 0) else 5.0
    macd_norm = np.clip(macd_hist / divisor, -1, 1)
    macd_score = (macd_norm + 1) / 2 * 100
    bb_score = np.clip(pct_b * 100, 0, 100)
    composite = 0.40 * rsi_score + 0.35 * macd_score + 0.25 * bb_score
    return round(composite, 1)

def interpret_signal(score, ticker=None):
    if score < 28: return "STRONG BUY", "🔥🔥"
    if score < 38: return "BUY", "🔥"
    if score < 48: return "WATCH", "👀"
    if score < 62: return "HOLD", "➖"
    if score < 75: return "REDUCE", "⚠️"
    return "WAIT", "🛑"

# ==============================================
#   MARKET MOOD
# ==============================================

def get_market_mood():
    try:
        r    = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        data = r.json()['data'][0]
        score  = int(data['value'])
        rating = data['value_classification']
        return score, rating
    except Exception: return None, None

def mood_emoji(score):
    if score is None: return "❓"
    if score < 20: return "😱"
    if score < 40: return "😨"
    if score < 60: return "😐"
    if score < 80: return "😏"
    return "🤑"

def mood_color(score):
    if score is None: return 0x888888
    if score < 30: return 0x2196F3
    if score < 45: return 0x9C27B0
    if score < 55: return 0xFFEB3B
    if score < 70: return 0xFF9800
    return 0xF44336

# ==============================================
#   AI COMMENTARY (Groq - FREE)
# ==============================================

def generate_ai_commentary(market_data: dict) -> str:
    if not GROQ_API_KEY: return "_⚠️ ไม่มี GROQ_API_KEY — ข้าม AI commentary_"
    dxy_price  = market_data.get('dxy', {}).get('price', 'N/A')
    dxy_trend  = market_data.get('dxy', {}).get('trend', 'N/A')
    month_year = market_data.get('month_year', 'Current Market')

    prompt = f"""You are a Senior Quantitative Strategist. Analyze this market data:
{json.dumps(market_data, indent=2, ensure_ascii=False)}

TASK: Write a 5-bullet Discord update in a Professional Thai-English mix.
LOGIC & CONTEXT ({month_year}):
1. **Sentiment:** สรุป Fear & Greed ({market_data.get('mood_score', 'N/A')}/100)
2. **Intermarket:** DXY {dxy_price} (trend: {dxy_trend}) กดดัน QQQM/GOLD อย่างไร
3. **Signals:** เจาะจงตัวที่มี Signal น่าสนใจ
4. **Gold Context:** GC=F ในฐานะ Safe Haven
5. **Action Plan:** คำแนะนำแบบ Engineer สำหรับชาว DCA

GUIDELINES: กระชับ เน้นตัวเลข ผสมไทย-อังกฤษ ใช้ Emoji นำหน้าทุกข้อ"""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 500, "temperature": 0.4,
                "messages": [
                    {"role": "system", "content": "You are a quant analyst explaining 'WHY' assets move based on DXY and RSI."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e: return f"_⚠️ AI commentary error: {e}_"

# ==============================================
#   STATE & DISCORD
# ==============================================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f: return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f: json.dump(state, f, indent=2)

def send_discord_embed(embeds: list, content: str = ""):
    if not DISCORD_WEBHOOK_URL: return
    payload = {
        "username": "Engineer Wealth Bot V5.0",
        "avatar_url": "https://raw.githubusercontent.com/purePutthipong/Engineer-Wealth-Bot/main/assets/bot_avatar.png",
        "content": content, "embeds": embeds,
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        r.raise_for_status()
    except Exception as e: print(f"❌ Discord error: {e}")

def build_code_block(rows: list, header: str) -> str:
    return f"```\n{header}\n{'─' * len(header)}\n" + "\n".join(rows) + "\n```"

def send_free_digest(free_rows: list, mood_score, mood_display: str, risk_label: str, risk_icon: str):
    """Phase 1: Free tier — QQQM+SMH digest only, no AI commentary."""
    if not DISCORD_FREE_WEBHOOK_URL:
        return

    thai_now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    date_str = thai_now.strftime('%d %b %Y')
    time_str = thai_now.strftime('%H:%M')

    fields = [
        {
            "name": f"🌡️ Risk Level: {risk_label} {risk_icon}",
            "value": "Weighted factor from RSI and Fear & Greed Index",
            "inline": False,
        },
        {
            "name": "📊 DCA Portfolio Signals",
            "value": build_code_block(free_rows, f"{'Asset':<6} {'Price':>8} {'%Chg':>7}"),
            "inline": False,
        },
        {
            "name": "🔒 Pro Features",
            "value": "✨ **Upgrade to Pro** for:\n• PLTR + ARM signals\n• Custom tickers\n• AI Commentary\n• Rotate alerts\n👉 [Subscribe $9.99/month](https://ko-fi.com/engineerwealthbot)",
            "inline": False,
        },
    ]

    payload = {
        "username": "Engineer Wealth Bot (Free)",
        "avatar_url": "https://raw.githubusercontent.com/purePutthipong/Engineer-Wealth-Bot/main/assets/bot_avatar.png",
        "embeds": [{
            "title": "⚙️ ENGINEER WEALTH BOT — Free Daily Digest",
            "description": f"📅 **{date_str}** `{time_str} ICT`\n🌡️ **Market Mood:** `{mood_display}`",
            "color": mood_color(mood_score),
            "fields": fields,
            "footer": {"text": "Free Tier • Upgrade for full signals + AI commentary"},
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }],
    }

    try:
        r = requests.post(DISCORD_FREE_WEBHOOK_URL, json=payload, timeout=15)
        r.raise_for_status()
        print("✅ Free digest sent")
    except Exception as e:
        print(f"❌ Free Discord error: {e}")

# ==============================================
#   MAIN
# ==============================================

def get_portfolio_dashboard():
    thai_now  = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    date_str  = thai_now.strftime('%d %b %Y')
    month_year = thai_now.strftime('%B %Y')
    time_str  = thai_now.strftime('%H:%M')
    is_friday = thai_now.weekday() == 4

    mood_score, mood_rating = get_market_mood()
    mood_display = f"{mood_score}/100 {mood_emoji(mood_score)} {mood_rating}" if mood_score else "N/A"

    prev_state = load_state()
    new_state  = {}

    tactical_rows = []
    free_rows     = []   # NEW: for free channel
    trend_rows    = []
    volume_alerts = []
    weekly_rows   = []
    rotate_alerts = []
    rsi_values    = []
    market_data_for_ai = {"date": date_str, "month_year": month_year, "mood_score": mood_score, "mood_rating": mood_rating, "assets": []}

    for ticker in TREND_TICKERS:
        try:
            stock = yf.Ticker(ticker)
            df    = stock.history(period="2y")
            if df.empty: continue

            name = DISPLAY_NAME.get(ticker, ticker)
            current_price = df['Close'].iloc[-1]
            prev_price = df['Close'].iloc[-2]
            change_pct = (current_price - prev_price) / prev_price * 100

            ma120 = df['Close'].rolling(120).mean().iloc[-1]
            pct_str = f"{(current_price - ma120) / ma120 * 100:+.1f}%" if not pd.isna(ma120) else "-"
            trend_icon = "🟢" if (not pd.isna(ma120) and current_price > ma120) else "🔴"

            trend_rows.append(f"{trend_icon} {name:<5} {current_price:>8.1f} {ma120:>8.2f} {pct_str:>7}")

            if ticker not in NO_VOLUME_TICKERS and 'Volume' in df.columns and len(df) >= 21:
                vol_today = df['Volume'].iloc[-1]
                vol_avg20 = df['Volume'].iloc[-21:-1].mean()
                if vol_avg20 > 0 and vol_today > vol_avg20 * 1.5:
                    volume_alerts.append(f"⚡ **{name}** Volume spike `{vol_today/vol_avg20:.1f}x` avg20")

            if ticker in PORT_TICKERS:
                rsi = calculate_rsi(df['Close']).iloc[-1]
                rsi_values.append(rsi)
                _, _, macd_hist_series = calculate_macd(df['Close'])
                macd_hist = macd_hist_series.iloc[-1]
                _, _, pct_b_series = calculate_bollinger(df['Close'])
                pct_b = pct_b_series.iloc[-1]
                score = compute_signal_score(rsi, macd_hist, pct_b, macd_hist_series.tail(30).std())
                signal, icon = interpret_signal(score)

                prev_signal = prev_state.get(ticker, {}).get('signal', None)
                new_state[ticker] = {'signal': signal, 'rsi': round(rsi, 1), 'score': score}

                display_signal = f"{prev_signal}→{signal}" if prev_signal and prev_signal != signal else signal
                chg_icon = "▲" if change_pct > 0 else "▼"
                tactical_rows.append(f"**{name}** {current_price:>8.2f} {chg_icon}{abs(change_pct):>4.1f}%\n└ RSI:{rsi:>4.1f} Score:{score:>4} {icon} {display_signal}")

                if ticker in FREE_TICKERS:
                    free_rows.append(f"**{name}** {current_price:>8.2f} {chg_icon}{abs(change_pct):>4.1f}%\n└ RSI:{rsi:>4.1f} Score:{score:>4} {icon} {display_signal}")

                market_data_for_ai["assets"].append({"ticker": name, "price": round(current_price, 2), "rsi": round(rsi, 1), "signal_score": score, "signal": signal})

                if is_friday:
                    prev_rsi = prev_state.get(ticker, {}).get('rsi', None)
                    weekly_rows.append(f"{name:<6} Score:{score:>5} RSI:{rsi:>5.1f}({rsi - prev_rsi if prev_rsi else 0:+.1f}) {icon} {signal}")

            if ticker in ROTATE_TARGETS:
                rt = ROTATE_TARGETS[ticker]
                trailing_stop = calculate_trailing_stop(df)
                gain_pct = (current_price - rt['cost']) / rt['cost'] * 100
                if current_price >= rt['target']:
                    rotate_alerts.append(f"🚀 **{name}** ถึงเป้า Rotate! `${current_price:.2f}` ≥ `${rt['target']}` (+{gain_pct:.1f}%)")
                elif current_price <= trailing_stop:
                    rotate_alerts.append(f"🛑 **{name}** หลุด Trailing Stop! `${current_price:.2f}` ≤ `${trailing_stop:.2f}` ({gain_pct:.1f}%)")
                else:
                    rotate_alerts.append(f"🛡️ **{name}** Trailing Stop: `${trailing_stop:.2f}` (Current: `${current_price:.2f}`)")

            if ticker == 'DX-Y.NYB':
                market_data_for_ai["dxy"] = {"price": round(current_price, 2), "trend": "up" if current_price > ma120 else "down"}

        except Exception as e: print(f"❌ Error {ticker}: {e}")

    save_state(new_state)
    ai_commentary = generate_ai_commentary(market_data_for_ai)
    risk_label, risk_icon = calculate_risk_level(np.mean(rsi_values) if rsi_values else None, mood_score)

    fields = [
        {"name": f"🌡️ Risk Level: {risk_label} {risk_icon}", "value": f"Weighted factor from Average RSI ({round(np.mean(rsi_values),1) if rsi_values else 'N/A'}) and Fear & Greed.", "inline": False},
        {"name": "📊 Tactical Dashboard", "value": build_code_block(tactical_rows, f"{'Asset':<6} {'Price':>8} {'%Chg':>7}"), "inline": False},
        {"name": "📉 Trend Analysis", "value": build_code_block(trend_rows, f" {'Asset':<5} {'Price':>8} {'MA120':>8} {'vs120':>7}"), "inline": False},
        {"name": "🤖 AI Commentary", "value": ai_commentary or "_No data_", "inline": False},
    ]

    if rotate_alerts: fields.append({"name": "🔄 Rotation & Protection", "value": "\n".join(rotate_alerts), "inline": False})
    if volume_alerts: fields.append({"name": "⚡ Volume Spike", "value": "\n".join(volume_alerts), "inline": False})
    if weekly_rows:   fields.append({"name": "📆 Weekly Summary (Friday)", "value": build_code_block(weekly_rows, f"{'Asset':<6} {'Score':>8} {'RSI':>9} Signal"), "inline": False})

    send_discord_embed([{
        "title": "⚙️ ENGINEER WEALTH BOT V5.0",
        "description": f"📅 **{date_str}** `{time_str} ICT`\n🌡️ **Market Mood:** `{mood_display}`",
        "color": mood_color(mood_score), "fields": fields,
        "footer": {"text": "Engineer Wealth Bot V5.0 • Data: Yahoo Finance + alternative.me"},
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }])
    
    # Send Free Digest (NEW V6)
    send_free_digest(free_rows, mood_score, mood_display, risk_label, risk_icon)

if __name__ == "__main__":
    get_portfolio_dashboard()
