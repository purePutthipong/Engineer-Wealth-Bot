import yfinance as yf
import pandas as pd
import requests
import datetime
import os

# --- ⚙️ HELPER FUNCTIONS ---
def get_env_float(key, default=0.0):
    val = os.environ.get(key)
    try:
        if val and val.strip() != "":
            return float(val)
    except: pass
    return default

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_market_mood():
    """ดึงค่า Fear & Greed Index จาก CNN"""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        score = int(data['fear_and_greed']['score'])
        rating = data['fear_and_greed']['rating']
        return score, rating
    except:
        return None, None

# --- ⚙️ CONFIGURATION ---
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')

MY_HOLDINGS = {
    'QQQM': {
        'qty': get_env_float('INPUT_QQQM_QTY', 0.0),
        'cost': get_env_float('INPUT_QQQM_COST', 0.0)
    },
    'SMH': {
        'qty': get_env_float('INPUT_SMH_QTY', 0.0),
        'cost': get_env_float('INPUT_SMH_COST', 0.0)
    },
    'CASH': get_env_float('INPUT_CASH_BALANCE', 175.04)
}

PORT_TICKERS = ['QQQM', 'SMH']
TREND_TICKERS = ['^NDX', 'QQQM', 'SMH'] 

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL: return
    data = {"content": content[:2000], "username": "Engineer Wealth Bot V2.7", "avatar_url": "https://cdn-icons-png.flaticon.com/512/2554/2554037.png"}
    requests.post(DISCORD_WEBHOOK_URL, json=data)

def get_portfolio_dashboard():
    print(f"🔄 Analyzing Portfolio & Market Mood...")
    
    # 1. Get Market Mood
    mood_score, mood_rating = get_market_mood()
    mood_text = "N/A"
    if mood_score is not None:
        # กำหนด Emoji ตามอารมณ์ตลาด
        if mood_score < 25: emoji = "😨" # Extreme Fear
        elif mood_score < 45: emoji = "😰" # Fear
        elif mood_score > 75: emoji = "🤑" # Extreme Greed
        elif mood_score > 55: emoji = "😏" # Greed
        else: emoji = "😐" # Neutral
        mood_text = f"`{mood_score}/100` {emoji} {mood_rating}"

    tactical_rows = [] 
    trend_rows = []    
    total_port_value = MY_HOLDINGS['CASH']
    
    for ticker in TREND_TICKERS:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="2y")
            if df.empty: continue
            
            # --- TREND ANALYSIS ---
            ma120 = df['Close'].rolling(window=120).mean().iloc[-1]
            ma250 = df['Close'].rolling(window=250).mean().iloc[-1]
            current_price = df['Close'].iloc[-1]
            
            display_name = "NDX100" if ticker == "^NDX" else ticker
            is_uptrend = current_price > ma120 if not pd.isna(ma120) else False
            trend_icon = "🟢" if is_uptrend else "🔴"
            ma120_str = f"{ma120:.2f}" if not pd.isna(ma120) else "-"
            ma250_str = f"{ma250:.2f}" if not pd.isna(ma250) else "-"
            
            trend_rows.append(f"{trend_icon} {display_name:<6} {ma120_str:>9} {ma250_str:>9}")

            # --- TACTICAL DASHBOARD ---
            if ticker in PORT_TICKERS:
                rsi = calculate_rsi(df['Close']).iloc[-1]
                prev_price = df['Close'].iloc[-2]
                change_pct = ((current_price - prev_price) / prev_price) * 100
                
                qty = MY_HOLDINGS[ticker]['qty']
                total_port_value += (qty * current_price)
                
                signal = "HOLD"
                icon = "➖"
                if rsi < 35: signal, icon = "BUY", "🔥"
                elif rsi < 45 and ticker == 'SMH': signal, icon = "WATCH", "👀"
                elif rsi > 70: signal, icon = "WAIT", "⚠️"
                
                tactical_rows.append(f"{ticker:<6} {current_price:>8.2f} {change_pct:>7.1f}% {rsi:>4.0f}  {icon} {signal}")

        except Exception as e:
            print(f"❌ Error {ticker}: {e}")

    # --- BUILD MESSAGE ---
    utc_now = datetime.datetime.utcnow()
    thai_now = utc_now + datetime.timedelta(hours=7)
    date_str = thai_now.strftime('%Y-%m-%d')
    
    msg = f"🤖 **ENGINEER WEALTH BOT V2.7**\n"
    msg += f"📅 {date_str} (Asia/Bangkok)\n"
    msg += f"🌡️ **Market Mood:** {mood_text}\n\n" # เพิ่มบรรทัดนี้
    
    # Table 1: Tactical Dashboard
    msg += "**📊 Tactical Dashboard**\n```\n"
    msg += f"{'Asset':<6} {'Price':>8} {'%Chg':>8} {'RSI':>4}  {'Signal'}\n"
    msg += "-"*39 + "\n" 
    for row in tactical_rows:
        msg += row + "\n"
    msg += "```\n"

    # Table 2: Trend Analysis
    msg += "**📉 Trend Analysis**\n```\n"
    msg += f"{'Asset':<9} {'MA120':>9} {'MA250':>9}\n"
    msg += "-"*29 + "\n"
    for row in trend_rows:
        msg += row + "\n"
    msg += "```\n"
    
    msg += f"💰 **Total Wealth:** `${total_port_value:.2f}`\n"
    msg += f"💵 **Buffer:** `${MY_HOLDINGS['CASH']:.2f}`"

    send_discord_alert(msg)

if __name__ == "__main__":
    get_portfolio_dashboard()
