import yfinance as yf
import pandas as pd
import numpy as np
import requests
import datetime
import json
import os

# ==============================================
#   Engineer Wealth Bot V5.0 (Full & Fixed)
#   - DCA Strategy: Bi-Weekly Support (S1, S2)
#   - Multi-factor Score: RSI + MACD + Bollinger
#   - AI Analysis: Groq (Llama 3.3)
#   - Fixed: Syntax Error & Gold Volume Bug
# ==============================================

DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')
GROQ_API_KEY        = os.environ.get('GROQ_API_KEY')
STATE_FILE          = "signal_state.json"

PORT_TICKERS  = ['QQQM', 'SMH', 'GC=F']
TREND_TICKERS = ['^NDX', 'QQQM', 'SMH', 'GC=F', 'DX-Y.NYB']

DISPLAY_NAME = {
    '^NDX':      'NDX100',
    'DX-Y.NYB':  'DXY',
    'QQQM':      'QQQM',
    'SMH':       'SMH',
    'GC=F':      'GOLD',
}

# ข้าม ticker ที่ไม่มีข้อมูล Volume ที่เชื่อถือได้ใน Yahoo Finance
NO_VOLUME_TICKERS = {'GC=F', '^NDX', 'DX-Y.NYB'}

# ==============================================
#   INDICATORS
# ==============================================

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger(series, period=20, std_dev=2):
    ma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    pct_b = (series - lower) / (upper - lower)
    return upper, lower, pct_b

def compute_signal_score(rsi, macd_hist, pct_b, macd_std=5.0):
    rsi_score = np.clip(rsi, 0, 100)
    divisor = macd_std if (macd_std and macd_std > 0) else 5.0
    macd_norm = np.clip(macd_hist / divisor, -1, 1)
    macd_score = (macd_norm + 1) / 2 * 100
    bb_score = np.clip(pct_b * 100, 0, 100)
    composite = 0.40 * rsi_score + 0.35 * macd_score + 0.25 * bb_score
    return round(composite, 1)

def interpret_signal(score):
    if score < 28: return "STRONG BUY", "🔥🔥"
    elif score < 38: return "BUY", "🔥"
    elif score < 48: return "WATCH", "👀"
    elif score < 62: return "HOLD", "➖"
    elif score < 75: return "REDUCE", "⚠️"
    else: return "WAIT", "🛑"

# ==============================================
#   AI COMMENTARY
# ==============================================

def generate_ai_commentary(market_data: dict) -> str:
    if not GROQ_API_KEY: return "_⚠️ ไม่มี GROQ_API_KEY — ข้าม AI commentary_"
    
    prompt = f"""You are a Senior Quantitative Strategist. Analyze this data for a 2-week DCA strategy:
{json.dumps(market_data, indent=2, ensure_ascii=False)}

TASK: Write a 5-bullet Discord update in Professional Thai-English mix.
1. Sentiment & Mood impact (Fear/Greed).
2. DXY vs Tech and Gold dynamics.
3. Support Analysis: Check 'dist_to_s1'. If negative, mention as a 'Buy Opportunity'.
4. DCA advice: Based on current Signal Score and 2-week pivots.
5. Engineer-style actionable takeaway."""

    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 500, "temperature": 0.4,
                "messages": [
                    {"role": "system", "content": "You are a quant strategist. Explain why assets move relative to DXY and 2-week support targets."},
                    {"role": "user", "content": prompt}
                ]
            }, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e: return f"_⚠️ AI commentary error: {e}_"

# ==============================================
#   MAIN ENGINE
# ==============================================

def get_portfolio_dashboard():
    thai_now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    date_str, time_str = thai_now.strftime('%d %b %Y'), thai_now.strftime('%H:%M')
    is_friday = thai_now.weekday() == 4

    # Fetch Market Mood
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        mood_data = r.json()['data'][0]
        mood_score = int(mood_data['value'])
        mood_rating = mood_data['value_classification']
    except:
        mood_score, mood_rating = None, "N/A"

    tactical_rows, trend_rows, volume_alerts, weekly_rows = [], [], [], []
    market_data_for_ai = {"date": date_str, "mood_score": mood_score, "assets": []}

    for ticker in TREND_TICKERS:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="1y")
            if df.empty: continue

            name = DISPLAY_NAME.get(ticker, ticker)
            curr = df['Close'].iloc[-1]
            prev = df['Close'].iloc[-2]
            change_pct = (curr - prev) / prev * 100

            # Trend Analysis
            ma120 = df['Close'].rolling(120).mean().iloc[-1]
            trend_icon = "🟢" if curr > ma120 else "🔴"
            vs120_pct = (curr - ma120) / ma120 * 100 if not pd.isna(ma120) else 0
            trend_rows.append(f"{trend_icon} {name:<5} {curr:>8.1f} {ma120:>8.1f} {vs120_pct:>7.1f}%")

            # Volume Spike (Skip NO_VOLUME_TICKERS)
            if ticker not in NO_VOLUME_TICKERS and 'Volume' in df.columns and len(df) >= 21:
                v_today, v_avg = df['Volume'].iloc[-1], df['Volume'].iloc[-21:-1].mean()
                if v_avg > 0 and v_today > v_avg * 1.5:
                    volume_alerts.append(f"⚡ **{name}** Vol spike `{v_today/v_avg:.1f}x`")

            # Tactical & 2-Week Support (Portfolio only)
            if ticker in PORT_TICKERS:
                rsi = calculate_rsi(df['Close']).iloc[-1]
                _, _, mh_series = calculate_macd(df['Close'])
                _, _, pb_series = calculate_bollinger(df['Close'])
                score = compute_signal_score(rsi, mh_series.iloc[-1], pb_series.iloc[-1], mh_series.tail(30).std())
                signal, icon = interpret_signal(score)

                # Bi-Weekly Support Calculation
                df_2w = df.resample('2W-SUN').agg({'High':'max', 'Low':'min', 'Close':'last'})
                w2 = df_2w.iloc[-2] # แท่ง 2 สัปดาห์ก่อนหน้าที่จบสมบูรณ์แล้ว
                pivot = (w2['High'] + w2['Low'] + w2['Close']) / 3
                s1, s2 = (pivot * 2) - w2['High'], pivot - (w2['High'] - w2['Low'])
                dist_s1 = (curr - s1) / s1 * 100

                tactical_rows.append(
                    f"**{name}** {curr:>8.2f} {'▲' if change_pct > 0 else '▼'}{abs(change_pct):>4.1f}%\n"
                    f"└ RSI:{rsi:>4.1f} Score:{score:>4} {icon} {signal}\n"
                    f"  🛡️ **2-Week Sup:** S1:{s1:.2f} ({dist_s1:+.1f}%) | S2:{s2:.2f}"
                )

                market_data_for_ai["assets"].append({
                    "ticker": name, "price": round(curr, 2), "score": score,
                    "s1": round(s1, 2), "dist_to_s1": round(dist_s1, 1)
                })

            if ticker == 'DX-Y.NYB':
                market_data_for_ai["dxy"] = {"price": round(curr, 2), "trend": "up" if curr > ma120 else "down"}

        except Exception as e:
            print(f"❌ Error {ticker}: {e}")

    # AI Commentary Generation
    ai_commentary = generate_ai_commentary(market_data_for_ai)

    # UI Construction
    trend_header = f" Asset   Price    MA120    vs120"
    trend_block  = f"```\n{trend_header}\n{'─' * len(trend_header)}\n" + "\n".join(trend_rows) + "\n```"
    
    embed = {
        "title": "⚙️ ENGINEER WEALTH BOT V5.0",
        "description": f"📅 **{date_str}** `{time_str} ICT` | 🌡️ Mood: `{mood_score}/100`",
        "color": 0x2196F3 if (mood_score or 50) < 30 else 0xFFEB3B if (mood_score or 50) < 60 else 0xF44336,
        "fields": [
            {"name": "📊 Tactical Dashboard (2-Week Targets)", "value": "\n".join(tactical_rows) if tactical_rows else "N/A", "inline": False},
            {"name": "📉 Trend Analysis", "value": trend_block, "inline": False},
            {"name": "🤖 AI Commentary", "value": ai_commentary, "inline": False},
        ],
        "footer": {"text": "DCA Strategy • Pivot Points: Bi-Weekly Basis"},
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

    if volume_alerts:
        embed["fields"].insert(2, {"name": "⚡ Volume Spike", "value": "\n".join(volume_alerts), "inline": False})

    # Send to Discord
    requests.post(DISCORD_WEBHOOK_URL, json={"username": "Engineer Wealth Bot V5.0", "embeds": [embed]}, timeout=15)
    print("✅ Dashboard Sent to Discord!")

if __name__ == "__main__":
    get_portfolio_dashboard()
