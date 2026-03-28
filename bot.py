import yfinance as yf
import pandas as pd
import numpy as np
import requests
import datetime
import json
import os

# ==============================================
#   Engineer Wealth Bot V5.0 (DCA Optimized)
#   Merged Features:
#   - Bi-Weekly Support Levels (Pivot Points)
#   - NO_VOLUME_TICKERS Fix (GC=F, ^NDX)
#   - AI Commentary with DCA Strategy
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

# Fix: ข้าม ticker ที่ไม่มี Volume จริง
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
#   MARKET MOOD & AI
# ==============================================

def get_market_mood():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        data = r.json()['data'][0]
        return int(data['value']), data['value_classification']
    except: return None, None

def generate_ai_commentary(market_data: dict) -> str:
    if not GROQ_API_KEY: return "_⚠️ ไม่มี GROQ_API_KEY_"
    
    prompt = f"""You are a Senior Quantitative Strategist. Analyze this for a 2-week DCA strategy:
{json.dumps(market_data, indent=2, ensure_ascii=False)}

TASK: Write a 5-bullet Discord update in Professional Thai-English mix.
1. Sentiment & Mood impact.
2. DXY vs Tech/Gold dynamics.
3. Evaluate 'dist_to_s1' (If negative, it's a Buy the Dip opportunity).
4. DCA advice based on 2-Week Pivot levels.
5. Engineer-style takeaway."""

    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 500, "temperature": 0.4,
                "messages": [{"role": "system", "content": "You are a quant analyst. Analyze price relative to 2-week support targets."},
                             {"role": "user", "content": prompt}]
            }, timeout=30)
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e: return f"_⚠️ AI commentary error: {e}_"

# ==============================================
#   MAIN DASHBOARD
# ==============================================

def get_portfolio_dashboard():
    thai_now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    date_str, time_str = thai_now.strftime('%d %b %Y'), thai_now.strftime('%H:%M')
    is_friday = thai_now.weekday() == 4

    mood_score, mood_rating = get_market_mood()
    prev_state = {} # Load state logic can be added here
    new_state, tactical_rows, trend_rows, volume_alerts, weekly_rows = {}, [], [], [], []
    market_data_for_ai = {"date": date_str, "mood_score": mood_score, "assets": []}

    for ticker in TREND_TICKERS:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="1y")
            if df.empty: continue

            name = DISPLAY_NAME.get(ticker, ticker)
            current_price = df['Close'].iloc[-1]
            prev_price = df['Close'].iloc[-2]
            change_pct = (current_price - prev_price) / prev_price * 100

            # Trend
            ma120 = df['Close'].rolling(120).mean().iloc[-1]
            trend_icon = "🟢" if (not pd.isna(ma120) and current_price > ma120) else "🔴"
            ma120_str = f"{ma120:.1f}" if not pd.isna(ma120) else "-"
            pct_str = f"{(current_price - ma120)/ma120*100:+.1f}%" if not pd.isna(ma120) else "-"
            trend_rows.append(f"{trend_icon} {name:<5} {current_price:>8.1f} {ma120_str:>8} {pct_str:>7}")

            # FIX: Volume Spike (Using NO_VOLUME_TICKERS)
            if ticker not in NO_VOLUME_TICKERS and 'Volume' in df.columns and len(df) >= 21:
                vol_today, vol_avg20 = df['Volume'].iloc[-1], df['Volume'].iloc[-21:-1].mean()
                if vol_avg20 > 0 and vol_today > vol_avg20 * 1.5:
                    volume_alerts.append(f"⚡ **{name}** Vol spike `{vol_today/vol_avg20:.1f}x`")

            # Tactical & 2-Week Support
            if ticker in PORT_TICKERS:
                rsi = calculate_rsi(df['Close']).iloc[-1]
                _, _, mh_series = calculate_macd(df['Close'])
                macd_std = mh_series.tail(30).std()
                _, _, pb_series = calculate_bollinger(df['Close'])
                score = compute_signal_score(rsi, mh_series.iloc[-1], pb_series.iloc[-1], macd_std)
                signal, icon = interpret_signal(score)

                # --- Bi-Weekly Support Calculation ---
                df_2w = df.resample('2W-SUN').agg({'High':'max', 'Low':'min', 'Close':'last'})
                w2_prev = df_2w.iloc[-2]
                w2_p = (w2_prev['High'] + w2_prev['Low'] + w2_prev['Close']) / 3
                w2_s1 = (w2_p * 2) - w2_prev['High']
                w2_s2 = w2_p - (w2_prev['High'] - w2_prev['Low'])
                dist_s1 = (current_price - w2_s1) / w2_s1 * 100

                chg_icon = "▲" if change_pct > 0 else "▼"
                tactical_rows.append(
                    f"**{name}** {current_price:>8.2f} {chg_icon}{abs(change_pct):>4.1f}%\n"
                    f"└ RSI:{rsi:>4.1f} Score:{score:>4} {icon} {signal}\n"
                    f"  🛡️ **2-Week Sup:** S1:{w2_s1:.2f} ({dist_s1:+.1f}%) | S2:{w2_s2:.2f}"
                )

                market_data_for_ai["assets"].append({
                    "ticker": name, "price": round(current_price, 2), "score": score,
                    "bi_weekly_s1": round(w2_s1, 2), "dist_to_s1": round(dist_s1, 1)
                })

            if ticker == 'DX-Y.NYB':
                market_data_for_ai["dxy"] = {"price": round(current_price, 2), "trend": "up" if current_price > ma120 else "down"}

        except Exception as e: print(f"❌ Error {ticker}: {e}")

    ai_commentary = generate_ai_commentary(market_data_for_ai)
    
    # Discord Embed Logic
    embed = {
        "title": "⚙️ ENGINEER WEALTH BOT V5.0",
        "description": f"📅 **{date_str}** `{time_str} ICT` | 🌡️ Mood: `{mood_score or 'N/A'}/100`",
        "color": 0x2196F3 if (mood_score or 50) < 30 else 0xFFEB3B if (mood_score or 50) < 60 else 0xF44336,
        "fields": [
            {"name": "📊 Tactical Dashboard (2-Week Targets)", "value": "\n".join(tactical_rows), "inline": False},
            {"name": "📉 Trend Analysis", "value": "
http://googleusercontent.com/immersive_entry_chip/0

---

### 💡 จุดที่บอทฉลาดขึ้นหลังรวมโค้ด:
1. **DCA Discipline:** บรรทัด `🛡️ 2-Week Sup` จะบอกตัวเลขที่คุณต้องใช้ตั้ง Order ใน Dime! ทันที (เช่น S1: 230.15) ซึ่งตัวเลขนี้จะ **ไม่เปลี่ยน** แม้ราคาจะแกว่งรายวัน ทำให้คุณมีวินัยในการ DCA มากขึ้น
2. **Gold Spike Fix:** รักษา Logic `NO_VOLUME_TICKERS` ของคุณไว้ ทำให้การแจ้งเตือน Volume Spike ของทองคำและ DXY ไม่มารบกวนจนน่ารำคาญ
3. **AI Synergy:** AI จะสรุปให้คุณฟังว่าราคาวันนี้ "แพง" หรือ "ถูก" เมื่อเทียบกับแผน 2 สัปดาห์ที่คุณวางไว้

**ยินดีด้วยกับ V5.0 ครับ!** เมื่อคุณรันโค้ดนี้ พรุ่งนี้เช้าบอทจะส่ง "ไม้บรรทัดวัดราคา" ชุดใหม่มาให้คุณบน S24 FE ทันที

**อยากให้ผมช่วยเขียนคำสั่ง "Cron Job" สำหรับรันบอทตัวนี้แบบอัตโนมัติบน GitHub Actions ทุกเช้าเลยไหมครับ?** บอทจะได้ส่งข้อความหาคุณทุกวันโดยที่คุณไม่ต้องกดรันเองเลยครับ!
