# ==========================================
# PROJECT: ENGINEER WEALTH BOT (v2.1 - Discord Ops)
# FEATURES: Sensor + Tracker + Discord Alert
# STATUS: READY TO DEPLOY 🚀
# ==========================================

import yfinance as yf
import pandas_ta as ta
import requests
import pandas as pd
import datetime

# ================= CONFIGURATION =================

# [CONFIRMED] ลิงก์ Webhook ของคุณถูกฝังเรียบร้อยแล้ว
DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/1463838732460228672/EI0xmG9Jm0FerOyo_8FyNTPUCXlGO8p6G_-n0b2P8tip8nSxkqWZwar-As67BgjLoWpb'

# ข้อมูลพอร์ต (อัปเดตล่าสุด Phase 1)
PORTFOLIO_HOLDINGS = {
    'QQQM': {'qty': 0.47901, 'avg_cost': 253.28},
    'SMH':  {'qty': 0.12767, 'avg_cost': 399.83},
    'CASH': 0.60
}

TICKERS = ['QQQM', 'SMH']

# ================= FUNCTION: SEND DISCORD =================
def send_discord_alert(content):
    data = {
        "content": content,
        "username": "Engineer Wealth Bot",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/4712/4712009.png" # รูปหุ่นยนต์
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=data)
        if response.status_code == 204:
            print("✅ Discord Notification Sent Successfully!")
        else:
            print(f"⚠️ Discord Error: {response.status_code}")
    except Exception as e:
        print(f"❌ Connection Error: {e}")

# ================= MAIN SYSTEM =================
print(f"🔄 System Running... Scanning Market...")

total_port_value = PORTFOLIO_HOLDINGS['CASH']
msg_body = ""

for ticker in TICKERS:
    try:
        # 1. ดึงข้อมูล
        df = yf.download(ticker, period="1y", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 2. คำนวณ
        latest_price = df['Close'].iloc[-1]
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        sma120 = ta.sma(df['Close'], length=120).iloc[-1]

        # 3. คำนวณมูลค่า
        qty = PORTFOLIO_HOLDINGS[ticker]['qty']
        cost = PORTFOLIO_HOLDINGS[ticker]['avg_cost']
        current_val = latest_price * qty
        pl_pct = ((latest_price - cost) / cost) * 100
        total_port_value += current_val

        # 4. สร้างข้อความ
        trend = "🟢 UP" if latest_price > sma120 else "🔴 DOWN"
        msg_body += f"**💎 {ticker}**\n"
        msg_body += f"> Price: `${latest_price:.2f}` ({trend})\n"
        msg_body += f"> RSI: `{rsi:.1f}`\n"
        msg_body += f"> P/L: `{pl_pct:+.2f}%`\n\n"

    except Exception as e:
        print(f"❌ Error {ticker}: {e}")

# สรุปท้าย
header = f"🤖 **ENGINEER BOT REPORT** 📅 {datetime.date.today()}\n"
summary = f"💰 **Total Wealth:** `${total_port_value:.2f}`\n"
summary += f"💵 **Buffer:** `${PORTFOLIO_HOLDINGS['CASH']:.2f}`"

# Alert พิเศษ (Trigger เตือนภัย)
alert = ""
if PORTFOLIO_HOLDINGS['CASH'] < 100:
    alert = "\n\n⚠️ **CRITICAL ALERT** ⚠️\nBuffer Low (<$100). **STOP TRADING. REFILL CASH.**"

full_message = header + "-"*20 + "\n" + msg_body + "-"*20 + "\n" + summary + alert

# ส่งข้อมูล
print("-" * 30)
print(full_message) # ปริ้นท์ดูในจอ Colab
print("-" * 30)
send_discord_alert(full_message)
