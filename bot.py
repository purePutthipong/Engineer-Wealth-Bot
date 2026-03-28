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
#   - Bi-Weekly Support Levels (S1, S2) สำหรับ DCA
#   - % ห่างจาก S1 (จุด DCA เป้าหมาย)
#   - AI รับรู้ค่า S1/S2 วิเคราะห์ได้แม่นขึ้น
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

NO_VOLUME_TICKERS = {'GC=F', '^NDX', 'DX-Y.NYB'}

# ==============================================
#   INDICATORS
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
    ema_fast    = series.ewm(span=fast, adjust=False).mean()
    ema_slow    = series.ewm(span=slow, adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger(series, period=20, std_dev=2):
    ma    = series.rolling(window=period).mean()
    std   = series.rolling(window=period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    pct_b = (series - lower) / (upper - lower)
    return upper, lower, pct_b


def compute_signal_score(rsi, macd_hist, pct_b, macd_std=5.0):
    rsi_score  = np.clip(rsi, 0, 100)
    divisor    = macd_std if (macd_std and macd_std > 0) else 5.0
    macd_norm  = np.clip(macd_hist / divisor, -1, 1)
    macd_score = (macd_norm + 1) / 2 * 100
    bb_score   = np.clip(pct_b * 100, 0, 100)
    composite  = 0.40 * rsi_score + 0.35 * macd_score + 0.25 * bb_score
    return round(composite, 1)


def interpret_signal(score, ticker=None):
    if score < 28:   return "STRONG BUY", "🔥🔥"
    elif score < 38: return "BUY",        "🔥"
    elif score < 48: return "WATCH",      "👀"
    elif score < 62: return "HOLD",       "➖"
    elif score < 75: return "REDUCE",     "⚠️"
    else:            return "WAIT",       "🛑"


def calculate_biweekly_support(df):
    """
    คำนวณ S1, S2 จาก Pivot Point ของ 2 สัปดาห์ที่แล้ว
    S1/S2 จะคงที่ตลอดรอบ 2 สัปดาห์ เหมาะสำหรับตั้ง DCA order
    """
    df_2w = df.resample('2W-SUN').agg({'High': 'max', 'Low': 'min', 'Close': 'last'})
    if len(df_2w) < 2:
        return None, None
    w2    = df_2w.iloc[-2]
    pivot = (w2['High'] + w2['Low'] + w2['Close']) / 3
    s1    = (pivot * 2) - w2['High']
    s2    = pivot - (w2['High'] - w2['Low'])
    return s1, s2


# ==============================================
#   MARKET MOOD
# ==============================================

def get_market_mood():
    try:
        r      = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        data   = r.json()['data'][0]
        score  = int(data['value'])
        rating = data['value_classification']
        return score, rating
    except Exception:
        return None, None


def mood_emoji(score):
    if score is None: return "❓"
    if score < 20:    return "😱"
    if score < 40:    return "😨"
    if score < 60:    return "😐"
    if score < 80:    return "😏"
    return "🤑"


def mood_color(score):
    if score is None: return 0x888888
    if score < 30:    return 0x2196F3
    if score < 45:    return 0x9C27B0
    if score < 55:    return 0xFFEB3B
    if score < 70:    return 0xFF9800
    return 0xF44336


# ==============================================
#   AI COMMENTARY (Groq - FREE)
# ==============================================

def generate_ai_commentary(market_data: dict) -> str:
    if not GROQ_API_KEY:
        return "_⚠️ ไม่มี GROQ_API_KEY — ข้าม AI commentary_"

    prompt = f"""You are a Senior Quantitative Strategist. Analyze this market data:
{json.dumps(market_data, indent=2, ensure_ascii=False)}

TASK: Write a 5-bullet Discord update in a Professional Thai-English mix.
LOGIC & CONTEXT (March 2026):
1. 🌡️ **Sentiment:** สรุปความกลัวในตลาด (Extreme Fear) กระทบแรงซื้ออย่างไร
2. ⚔️ **Intermarket:** วิเคราะห์ว่า DXY ที่แข็งค่า (ตอนนี้ประมาณ 100.2) กดดัน QQQM และ GOLD อย่างไร
3. 🎯 **Signals:** เจาะจงตัวที่มี Score ต่ำกว่า 30 (เช่น QQQM/SMH ที่คุณได้มา)
4. 💰 **DCA Targets:** วิเคราะห์ S1/S2 ของแต่ละ asset ว่าราคาปัจจุบันอยู่ห่างจากจุด DCA แค่ไหน คุ้มซื้อไหม
5. 🛡️ **Action Plan:** คำแนะนำแบบ Engineer สำหรับชาว DCA ในสถานการณ์นี้

GUIDELINES:
- กระชับ ไม่เวิ่นเว้อ เน้นตัวเลข
- ผสมภาษาไทย-อังกฤษแบบธรรมชาติ
- ใช้ Emoji นำหน้าทุกข้อ"""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model":       "llama-3.3-70b-versatile",
                "max_tokens":  500,
                "temperature": 0.4,
                "messages": [
                    {"role": "system", "content": "You are a concise quant analyst who explains 'WHY' assets move based on DXY, RSI, and bi-weekly support levels."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"_⚠️ AI commentary error: {e}_"


# ==============================================
#   STATE
# ==============================================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ==============================================
#   DISCORD
# ==============================================

def send_discord_embed(embeds: list, content: str = ""):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ No DISCORD_WEBHOOK set")
        return
    payload = {
        "username":   "Engineer Wealth Bot V5.0",
        "avatar_url": "https://raw.githubusercontent.com/purePutthipong/Engineer-Wealth-Bot/main/assets/bot_avatar.png",
        "content":    content,
        "embeds":     embeds,
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        r.raise_for_status()
        print("✅ Discord embed sent!")
    except Exception as e:
        print(f"❌ Discord error: {e}")


def build_code_block(rows: list, header: str) -> str:
    return f"```\n{header}\n{'─' * len(header)}\n" + "\n".join(rows) + "\n```"


# ==============================================
#   MAIN
# ==============================================

def get_portfolio_dashboard():
    thai_now  = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    date_str  = thai_now.strftime('%d %b %Y')
    time_str  = thai_now.strftime('%H:%M')
    is_friday = thai_now.weekday() == 4

    print(f"🔄 Running... {date_str} {time_str} (Friday={is_friday})")

    mood_score, mood_rating = get_market_mood()
    mood_icon    = mood_emoji(mood_score)
    mood_display = f"{mood_score}/100  {mood_icon}  {mood_rating}" if mood_score else "N/A"

    prev_state = load_state()
    new_state  = {}

    tactical_rows      = []
    trend_rows         = []
    volume_alerts      = []
    weekly_rows        = []
    market_data_for_ai = {
        "date":        date_str,
        "mood_score":  mood_score,
        "mood_rating": mood_rating,
        "assets":      [],
    }

    for ticker in TREND_TICKERS:
        try:
            stock = yf.Ticker(ticker)
            df    = stock.history(period="2y")
            if df.empty:
                print(f"⚠️ No data: {ticker}")
                continue

            name          = DISPLAY_NAME.get(ticker, ticker)
            current_price = df['Close'].iloc[-1]
            prev_price    = df['Close'].iloc[-2]
            change_pct    = (current_price - prev_price) / prev_price * 100

            ma120          = df['Close'].rolling(120).mean().iloc[-1]
            ma250          = df['Close'].rolling(250).mean().iloc[-1]
            pct_from_ma120 = (current_price - ma120) / ma120 * 100 if not pd.isna(ma120) else None

            trend_icon = "🟢" if (not pd.isna(ma120) and current_price > ma120) else "🔴"
            ma120_str  = f"{ma120:.2f}"            if not pd.isna(ma120)         else "-"
            ma250_str  = f"{ma250:.2f}"            if not pd.isna(ma250)         else "-"
            pct_str    = f"{pct_from_ma120:+.1f}%" if pct_from_ma120 is not None else "-"

            trend_rows.append(
                f"{trend_icon} {name:<5} {current_price:>8.1f} {ma120_str:>8} {pct_str:>7}"
            )

            # Volume Spike
            if ticker not in NO_VOLUME_TICKERS and 'Volume' in df.columns and len(df) >= 21:
                vol_today = df['Volume'].iloc[-1]
                vol_avg20 = df['Volume'].iloc[-21:-1].mean()
                if vol_avg20 > 0 and vol_today > vol_avg20 * 1.5:
                    spike_x = vol_today / vol_avg20
                    volume_alerts.append(f"⚡ **{name}** Volume spike `{spike_x:.1f}x` avg20")

            # Tactical + S1/S2 (PORT_TICKERS only)
            if ticker in PORT_TICKERS:
                rsi_series = calculate_rsi(df['Close'])
                rsi        = rsi_series.iloc[-1]   # FIX: .iloc[-1] ให้ได้ float

                _, _, macd_hist_series = calculate_macd(df['Close'])
                macd_hist  = macd_hist_series.iloc[-1]
                macd_prev  = macd_hist_series.iloc[-2]
                macd_std   = macd_hist_series.tail(30).std()
                macd_cross = ("↑" if (macd_hist > 0 and macd_prev <= 0) else
                              "↓" if (macd_hist < 0 and macd_prev >= 0) else "")

                _, _, pct_b_series = calculate_bollinger(df['Close'])
                pct_b = pct_b_series.iloc[-1]

                score        = compute_signal_score(rsi, macd_hist, pct_b, macd_std)
                signal, icon = interpret_signal(score)

                prev_signal = prev_state.get(ticker, {}).get('signal', None)
                new_state[ticker] = {'signal': signal, 'rsi': round(rsi, 1), 'score': score}

                display_signal = signal
                if prev_signal and prev_signal != signal:
                    display_signal = f"{prev_signal}→{signal}"

                chg_icon = "▲" if change_pct > 0 else "▼"

                # Bi-Weekly Support (S1, S2)
                s1, s2 = calculate_biweekly_support(df)
                if s1 is not None and s2 is not None:
                    dist_s1 = (current_price - s1) / s1 * 100
                    support_line = f"  🛡️ S1:{s1:.2f} ({dist_s1:+.1f}%) | S2:{s2:.2f}"
                else:
                    support_line = ""

                tactical_rows.append(
                    f"**{name}** {current_price:>8.2f} {chg_icon}{abs(change_pct):>4.1f}%\n"
                    f"└ RSI:{rsi:>4.1f} Score:{score:>4} {icon} {display_signal}{macd_cross}\n"
                    f"{support_line}"
                )

                # Collect for AI
                ai_asset = {
                    "ticker":       name,
                    "price":        round(current_price, 2),
                    "change_pct":   round(change_pct, 2),
                    "rsi":          round(rsi, 1),
                    "macd_hist":    round(macd_hist, 4),
                    "bb_pct_b":     round(pct_b, 3),
                    "signal_score": score,
                    "signal":       signal,
                    "vs_ma120":     pct_str,
                }
                if s1 is not None:
                    ai_asset["s1"]         = round(s1, 2)
                    ai_asset["s2"]         = round(s2, 2)
                    ai_asset["dist_to_s1"] = round(dist_s1, 1)
                market_data_for_ai["assets"].append(ai_asset)

                if is_friday:
                    prev_rsi   = prev_state.get(ticker, {}).get('rsi', None)
                    rsi_change = f"{rsi - prev_rsi:+.1f}" if prev_rsi else "N/A"
                    weekly_rows.append(
                        f"{name:<6} Score:{score:>5}  RSI:{rsi:>5.1f}({rsi_change})  {icon} {signal}"
                    )

            if ticker == 'DX-Y.NYB':
                market_data_for_ai["dxy"] = {
                    "price":      round(current_price, 2),
                    "change_pct": round(change_pct, 2),
                    "trend":      "up" if current_price > ma120 else "down",
                }

        except Exception as e:
            print(f"❌ Error {ticker}: {e}")

    save_state(new_state)

    print("🤖 Generating AI commentary...")
    ai_commentary = generate_ai_commentary(market_data_for_ai)

    embed_color  = mood_color(mood_score)
    trend_header = f" {'Asset':<5} {'Price':>8} {'MA120':>8} {'vs120':>7}"

    tactical_value = "\n".join(tactical_rows) if tactical_rows else "_ไม่มีข้อมูล_"
    trend_block    = build_code_block(trend_rows, trend_header)

    fields = [
        {"name": "📊 Tactical Dashboard", "value": tactical_value,                "inline": False},
        {"name": "📉 Trend Analysis",     "value": trend_block,                   "inline": False},
        {"name": "🤖 AI Commentary",       "value": ai_commentary or "_No data_", "inline": False},
    ]

    if volume_alerts:
        fields.append({"name": "⚡ Volume Spike", "value": "\n".join(volume_alerts), "inline": False})

    if is_friday and weekly_rows:
        weekly_block = build_code_block(weekly_rows, f"{'Asset':<6} {'Score':>6}  {'RSI':>8}  Signal")
        fields.append({"name": "📆 Weekly Summary", "value": weekly_block, "inline": False})

    embed = {
        "title":       "⚙️ ENGINEER WEALTH BOT V5.0",
        "description": (
            f"📅 **{date_str}**  `{time_str} ICT`\n"
            f"🌡️ **Market Mood:** `{mood_display}`"
        ),
        "color":  embed_color,
        "fields": fields,
        "footer": {"text": "Engineer Wealth Bot V5.0 • Data: Yahoo Finance + alternative.me + Groq AI"},
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }

    send_discord_embed([embed])


if __name__ == "__main__":
    get_portfolio_dashboard()
