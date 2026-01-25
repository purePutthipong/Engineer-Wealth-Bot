import yfinance as yf
import pandas as pd
import requests
import datetime
import os

# --- ⚙️ HELPER FUNCTIONS (MATH CORE) ---
# ฟังก์ชันคำนวณ RSI และจัดรูปแบบตารางด้วยตัวเอง (ไม่ง้อ Library นอก)

def get_env_float(key, default=0.0):
    val = os.environ.get(key)
    try:
        if val and val.strip() != "":
            return float(val)
    except: pass
    return default

def calculate_rsi(series, period=14):
    """คำนวณ RSI ด้วยสูตรคณิตศาสตร์พื้นฐาน (Wilder's Smoothing)"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    
    # ใช้ Exponential Moving Average (EMA) เพื่อจำลองค่า RSI
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# --- ⚙️ CONFIGURATION ---
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')

# ดึงข้อมูลจาก GitHub Secrets
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

# รายชื่อหุ้นตาม Master Plan
TICKERS = ['QQQM', 'SMH']

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ No Webhook. Console only.")
        print(content)
        return
    
    data = {
        "content": content[:2000],
        "username": "Engineer Wealth Bot V2.4",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2554/2554037.png"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
    except Exception as e:
        print(f"❌ Webhook Error: {e}")

def get_portfolio_dashboard():
    print(f"🔄 Analyzing Portfolio (Native Mode)...")
    
    tactical_rows = [] 
    trend_rows = []    
    
    total_port_value = MY_HOLDINGS['CASH']
    
    for ticker in TICKERS:
        try:
            # 1. ดึงข้อมูลย้อนหลัง 2 ปี (เพื่อให้มีข้อมูลพอทำ MA250)
            stock = yf.Ticker(ticker)
            df = stock.history(period="2y")
            
            if df.empty: continue
            
            # 2. คำนวณค่าต่างๆ เอง (Manual Calculation)
            # RSI
            df['RSI'] = calculate_rsi(df['Close'])
            # SMA (Moving Average)
            df['SMA_120'] = df['Close'].rolling(window=120).mean()
            df['SMA_250'] = df['Close'].rolling(window=250).mean()
            
            # ดึงค่าล่าสุด
            current_price = df['Close'].iloc[-1]
            current_rsi = df['RSI'].iloc[-1]
            ma120 = df['SMA_120'].iloc[-1]
            ma250 = df['SMA_250'].iloc[-1]
            prev_price = df['Close'].iloc[-2]
            
            change_pct = ((current_price - prev_price) / prev_price) * 100
            
            # 3. คำนวณมูลค่าพอร์ต
            qty = MY_HOLDINGS[ticker]['qty']
            market_val = qty * current_price
            total_port_value += market_val
            
            # 4. สร้างสัญญาณ (Logic)
            signal = "HOLD"
            icon = "➖"
            if current_rsi < 35:
                signal = "BUY"
                icon = "🔥"
            elif current_rsi < 45 and ticker == 'SMH':
                signal = "WATCH"
                icon = "👀"
            elif current_rsi > 70:
                signal = "WAIT"
                icon = "⚠️"

            # 5. จัดหน้าตารางด้วย f-string (String Formatting)
            # :<6 ชิดซ้าย 6 ช่อง, :>8 ชิดขวา 8 ช่อง
            
            # ตาราง Tactical
            row_str = f"{ticker:<6} {current_price:>8.2f} {change_pct:>7.1f}% {current_rsi:>4.0f}  {icon} {signal}"
            tactical_rows.append(row_str)

            # ตาราง Trend
            trend_icon = "🟢" if (not pd.isna(ma120) and current_price > ma120) else "🔴"
            ma120_str = f"{ma120:.2f}" if not pd.isna(ma120) else "-"
            ma250_str = f"{ma250:.2f}" if not pd.isna(ma250) else "-"
            
            trend_row = f"{trend_icon} {ticker:<4} {ma120_str:>9} {ma250_str:>9}"
            trend_rows.append(trend_row)
            
        except Exception as e:
            print(f"❌ Error {ticker}: {e}")

    # --- สร้างข้อความส่ง Discord ---
    utc_now = datetime.datetime.utcnow()
    thai_now = utc_now + datetime.timedelta(hours=7)
    date_str = thai_now.strftime('%Y-%m-%d')
    
    msg = f"🤖 **ENGINEER WEALTH BOT V2.4** (Lite)\n"
    msg += f"📅 {date_str} (Asia/Bangkok)\n"
    msg += f"🛡️ **Protocol:** Master Plan (70/30)\n\n"
    
    # Table 1: Tactical Dashboard
    msg += "**📊 Tactical Dashboard**\n```\n"
    msg += f"{'Asset':<6} {'Price':>8} {'%Chg':>8} {'RSI':>4}  {'Signal'}\n"
    msg += "-"*42 + "\n"
    for row in tactical_rows:
        msg += row + "\n"
    msg += "```\n"

    # Table 2: Trend Analysis
    msg += "**📉 Trend Analysis**\n```\n"
    msg += f"{'Asset':<7} {'MA120':>9} {'MA250':>9}\n"
    msg += "-"*28 + "\n"
    for row in trend_rows:
        msg += row + "\n"
    msg += "```\n"
    
    msg += f"💰 **Total Wealth:** `${total_port_value:.2f}`\n"
    msg += f"💵 **Buffer:** `${MY_HOLDINGS['CASH']:.2f}`"

    send_discord_alert(msg)

if __name__ == "__main__":
    get_portfolio_dashboard()
