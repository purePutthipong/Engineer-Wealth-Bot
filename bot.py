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
    """คำนวณ RSI ด้วยสูตรคณิตศาสตร์พื้นฐาน"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

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

# รายชื่อหุ้นในพอร์ต (สำหรับ Tactical & Value)
PORT_TICKERS = ['QQQM', 'SMH']

# รายชื่อสำหรับดู Trend (เพิ่ม Nasdaq 100 ^NDX)
TREND_TICKERS = ['^NDX', 'QQQM', 'SMH'] 

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ No Webhook. Console only.")
        print(content)
        return
    data = {"content": content[:2000], "username": "Engineer Wealth Bot V2.5", "avatar_url": "https://cdn-icons-png.flaticon.com/512/2554/2554037.png"}
    try: requests.post(DISCORD_WEBHOOK_URL, json=data)
    except Exception as e: print(f"❌ Webhook Error: {e}")

def get_portfolio_dashboard():
    print(f"🔄 Analyzing Portfolio & Market Trend...")
    
    tactical_rows = [] 
    trend_rows = []    
    total_port_value = MY_HOLDINGS['CASH']
    
    # 1. Loop สำหรับ Trend Analysis (รวม ^NDX)
    for ticker in TREND_TICKERS:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="2y")
            if df.empty: continue
            
            # คำนวณ Trend (MA)
            ma120 = df['Close'].rolling(window=120).mean().iloc[-1]
            ma250 = df['Close'].rolling(window=250).mean().iloc[-1]
            current_price = df['Close'].iloc[-1]
            
            # Format ชื่อให้สวย (^NDX -> NDX)
            display_name = "NDX100" if ticker == "^NDX" else ticker
            
            # สร้างแถว Trend
            is_uptrend = current_price > ma120 if not pd.isna(ma120) else False
            trend_icon = "🟢" if is_uptrend else "🔴"
            ma120_str = f"{ma120:.2f}" if not pd.isna(ma120) else "-"
            ma250_str = f"{ma250:.2f}" if not pd.isna(ma250) else "-"
            
            trend_rows.append(f"{trend_icon} {display_name:<6} {ma120_str:>9} {ma250_str:>9}")

            # 2. Loop สำหรับ Tactical Dashboard (เฉพาะหุ้นที่มีในพอร์ต)
            if ticker in PORT_TICKERS:
                # คำนวณ RSI & Value
                rsi = calculate_rsi(df['Close']).iloc[-1]
                prev_price = df['Close'].iloc[-2]
                change_pct = ((current_price - prev_price) / prev_price) * 100
                
                # มูลค่าพอร์ต
                qty = MY_HOLDINGS[ticker]['qty']
                total_port_value += (qty * current_price)
                
                # Signal
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
    
    msg = f"🤖 **ENGINEER WEALTH BOT V2.5**\n"
    msg += f"📅 {date_str} (Asia/Bangkok)\n"
    msg += f"🛡️ **Protocol:** Master Plan (70/30)\n\n"
    
    # Table 1: Tactical Dashboard (ตัดเส้นขีดให้สั้นลงและพอดี)
    msg += "**📊 Tactical Dashboard**\n```\n"
    msg += f"{'Asset':<6} {'Price':>8} {'%Chg':>8} {'RSI':>4}  {'Signal'}\n"
    msg += "-"*41 + "\n" # ปรับความยาวเส้นให้พอดีเป๊ะ
    for row in tactical_rows:
        msg += row + "\n"
    msg += "```\n"

    # Table 2: Trend Analysis (เพิ่ม NDX100)
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
