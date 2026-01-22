import yfinance as yf
import pandas as pd
import requests
import datetime
import os

DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')

# ฟังก์ชันดึงค่าจาก GitHub Inputs
def get_config(env_key, default_val):
    val = os.environ.get(env_key)
    return float(val) if val and val.strip() != "" else default_val

# ตั้งค่าพอร์ตแบบไดนามิก 100% (ดึงค่าทุนเฉลี่ยและจำนวนหุ้นจากหน้าเว็บ)
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

# สูตรคำนวณ RSI แบบเขียนเองเพื่อความเสถียรบน GitHub Actions
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

print(f"🔄 System Running... DCA Sniper Mode Activated")
total_port_value = PORTFOLIO_HOLDINGS['CASH']
msg_body = ""
signals = []

for ticker in ['QQQM', 'SMH']:
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        latest_price = df['Close'].iloc[-1]
        rsi = calculate_rsi(df['Close']).iloc[-1]
        sma120 = df['Close'].rolling(window=120).mean().iloc[-1]
        
        # --- DCA SNIPER LOGIC ---
        # เงื่อนไข: RSI < 35 (ราคาถูก) และ ยืนเหนือ SMA120 (ขาขึ้น)
        is_uptrend = latest_price > sma120
        is_oversold = rsi < 35
        
        action_msg = ""
        if is_uptrend and is_oversold:
            action_msg = "\n🚨 **BUY SIGNAL DETECTED!** (Dip in Uptrend)"
            signals.append(ticker)
        elif not is_uptrend:
            action_msg = "\n⚠️ *Warning: Below SMA120 (Down Trend)*"
        
        # คำนวณพอร์ต
        qty = PORTFOLIO_HOLDINGS[ticker]['qty']
        cost = PORTFOLIO_HOLDINGS[ticker]['avg_cost']
        current_val = latest_price * qty
        pl_pct = ((latest_price - cost) / cost) * 100
        total_port_value += current_val

     # --- กำหนดตัวแปร trend ให้ถูกต้องก่อนนำไปใช้ ---
        trend = "🟢 UP" if is_uptrend else "🔴 DOWN"
        trend_text = "UP" if is_uptrend else "DOWN"
        trend_icon = "🟢" if is_uptrend else "🔴"

        # --- ปรับรูปแบบข้อความตามความต้องการของคุณ ---
        msg_body += f"**💎 {ticker}**\n"
        msg_body += f"Price: `${latest_price:.2f}` ({trend_icon} {trend_text})\n"
        msg_body += f"RSI: `{rsi:.1f}`\n"
        msg_body += f"P/L: `{pl_pct:+.2f}%` \n"
        msg_body += f"(Cost: `${cost:.2f}` | Qty: `{qty}`){action_msg}\n\n"
    except Exception as e: print(f"❌ Error {ticker}: {e}")

# สร้างส่วนสรุปข้อมูล
header = f"🤖 **ENGINEER BOT REPORT** 📅 {datetime.date.today()}\n"
if signals:
    header = f"🔥 **DCA SNIPER ALERT!** 🔥\n" + header

summary = f"💰 **Total Wealth:** `${total_port_value:.2f}`\n💵 **Buffer:** `${PORTFOLIO_HOLDINGS['CASH']:.2f}`"
alert = "\n\n⚠️ **CRITICAL ALERT**\nBuffer Low (<$100). **REFILL CASH.**" if PORTFOLIO_HOLDINGS['CASH'] < 100 else ""

send_discord_alert(header + "-"*20 + "\n" + msg_body + "-"*20 + "\n" + summary + alert)
