import yfinance as yf
import pandas as pd
import pandas_ta as ta
from tabulate import tabulate
import requests
import datetime
import os

# --- ⚙️ HELPER FUNCTION ---
# ฟังก์ชันช่วยดึงค่าจาก GitHub Secrets (แปลงเป็นตัวเลขให้อัตโนมัติ)
def get_env_float(key, default=0.0):
    val = os.environ.get(key)
    try:
        if val and val.strip() != "":
            return float(val)
    except:
        pass
    return default

# --- ⚙️ CONFIGURATION ---
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')

# ดึงข้อมูลจาก GitHub Environment Variables (ตาม V1)
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

# กฎเหล็ก 70/30 (Master Plan)
PORTFOLIO_CONFIG = {
    'QQQM': {'weight': 0.70, 'name': 'Nasdaq 100 (Core)'},
    'SMH':  {'weight': 0.30, 'name': 'Semiconductors (Turbo)'}
}
TICKERS = list(PORTFOLIO_CONFIG.keys())

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ No Webhook. Console only.")
        print(content)
        return
    
    data = {
        "content": content[:2000],
        "username": "Engineer Wealth Bot V2.3",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2554/2554037.png"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
    except Exception as e:
        print(f"❌ Webhook Error: {e}")

def get_portfolio_dashboard():
    print(f"🔄 Analyzing Portfolio (Data Source: GitHub Secrets)...")
    
    tactical_results = []
    trend_results = []
    total_port_value = MY_HOLDINGS['CASH']
    
    for ticker in TICKERS:
        try:
            # 1. Get Data (2 Years for MA250)
            stock = yf.Ticker(ticker)
            df = stock.history(period="2y")
            
            if df.empty: continue
            
            # 2. Indicators Calculation
            df.ta.rsi(length=14, append=True)
            df.ta.sma(length=120, append=True)
            df.ta.sma(length=250, append=True)
            
            current_price = df['Close'].iloc[-1]
            current_rsi = df['RSI_14'].iloc[-1]
            ma120 = df['SMA_120'].iloc[-1]
            ma250 = df['SMA_250'].iloc[-1]
            
            prev_price = df['Close'].iloc[-2]
            change_pct = ((current_price - prev_price) / prev_price) * 100
            
            # 3. Calculate Value & P/L
            qty = MY_HOLDINGS[ticker]['qty']
            avg_cost = MY_HOLDINGS[ticker]['cost']
            market_val = qty * current_price
            total_port_value += market_val
            
            # 4. Tactical Signal (RSI)
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

            tactical_results.append([
                ticker,
                f"{current_price:.2f}",
                f"{change_pct:+.1f}%",
                f"{current_rsi:.0f}",
                f"{icon} {signal}"
            ])

            # 5. Trend Signal (MA Check)
            trend_icon = "🟢" if (not pd.isna(ma120) and current_price > ma120) else "🔴"
            ma120_str = f"{ma120:.2f}" if not pd.isna(ma120) else "-"
            ma250_str = f"{ma250:.2f}" if not pd.isna(ma250) else "-"
            
            trend_results.append([
                f"{trend_icon} {ticker}",
                ma120_str,
                ma250_str
            ])
            
        except Exception as e:
            print(f"❌ Error {ticker}: {e}")

    # --- FORMAT OUTPUT ---
    utc_now = datetime.datetime.utcnow()
    thai_now = utc_now + datetime.timedelta(hours=7)
    date_str = thai_now.strftime('%Y-%m-%d')
    
    msg = f"🤖 **ENGINEER WEALTH BOT V2.3**\n"
    msg += f"📅 {date_str} (Asia/Bangkok)\n"
    msg += f"🛡️ **Protocol:** Master Plan (70/30)\n\n"
    
    # Table 1: Tactical Dashboard
    msg += "**📊 Tactical Dashboard**\n```\n"
    msg += tabulate(tactical_results, headers=["Asset", "Price", "%", "RSI", "Signal"], tablefmt="simple")
    msg += "\n```\n"

    # Table 2: Trend Analysis
    msg += "**📉 Trend Analysis (MA120/250)**\n```\n"
    msg += tabulate(trend_results, headers=["Asset", "MA120", "MA250"], tablefmt="simple")
    msg += "\n```\n"
    
    msg += f"💰 **Total Wealth:** `${total_port_value:.2f}`\n"
    msg += f"💵 **Buffer:** `${MY_HOLDINGS['CASH']:.2f}`"

    send_discord_alert(msg)

if __name__ == "__main__":
    get_portfolio_dashboard()
