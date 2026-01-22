import yfinance as yf
import pandas as pd
import requests
import datetime
import os

DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')

# ฟังก์ชันดึงค่าจาก GitHub
def get_config(env_key, default_val):
    val = os.environ.get(env_key)
    return float(val) if val and val.strip() != "" else default_val

# ตั้งค่าพอร์ตแบบไดนามิก 100%
PORTFOLIO_HOLDINGS = {
    'QQQM': {
        'qty': get_config('INPUT_QQQM_QTY', 0.47901), 
        'avg_cost': get_config('INPUT_QQQM_COST', 253.28)
    },
    'SMH': {
        'qty': get_config('INPUT_SMH_QTY', 0.12767), 
        'avg_cost': get_config('INPUT_SMH_COST', 399.83)
    },
    'CASH': get_config('INPUT_CASH_BALANCE', 100.00)
}

def calculate_rsi(data, window=14):
    delta = data.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=window-1, adjust=False).mean()
    ema_down = down.ewm(com=window-1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL: return
    data = {"content": content, "username": "Engineer Wealth Bot", "avatar_url": "https://cdn-icons-png.flaticon.com/512/4712/4712009.png"}
    requests.post(DISCORD_WEBHOOK_URL, json=data)

print(f"🔄 System Running... Control Panel Mode")
total_port_value = PORTFOLIO_HOLDINGS['CASH']
msg_body = ""

for ticker in ['QQQM', 'SMH']:
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        latest_price = df['Close'].iloc[-1]
        rsi = calculate_rsi(df['Close']).iloc[-1]
        sma120 = df['Close'].rolling(window=120).mean().iloc[-1]
        
        qty = PORTFOLIO_HOLDINGS[ticker]['qty']
        cost = PORTFOLIO_HOLDINGS[ticker]['avg_cost']
        current_val = latest_price * qty
        pl_pct = ((latest_price - cost) / cost) * 100
        total_port_value += current_val

        trend = "🟢 UP" if latest_price > sma120 else "🔴 DOWN"
        msg_body += f"**💎 {ticker}**\n> Price: `${latest_price:.2f}` ({trend})\n> RSI: `{rsi:.1f}`\n> P/L: `{pl_pct:+.2f}%` (Qty: {qty})\n\n"
    except Exception as e: print(f"❌ Error {ticker}: {e}")

header = f"🤖 **ENGINEER BOT REPORT** 📅 {datetime.date.today()}\n"
summary = f"💰 **Total Wealth:** `${total_port_value:.2f}`\n💵 **Buffer:** `${PORTFOLIO_HOLDINGS['CASH']:.2f}`"
alert = "\n\n⚠️ **CRITICAL ALERT** ⚠️\nBuffer Low (<$100). **STOP TRADING.**" if PORTFOLIO_HOLDINGS['CASH'] < 100 else ""
send_discord_alert(header + "-"*20 + "\n" + msg_body + "-"*20 + "\n" + summary + alert)
