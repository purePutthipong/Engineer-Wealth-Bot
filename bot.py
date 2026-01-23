import yfinance as yf
import pandas as pd
import requests
import datetime
import os

DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')

def get_config(env_key, default_val):
    val = os.environ.get(env_key)
    try:
        # ถ้ามีค่าส่งมาจาก GitHub (Env Var) ให้ใช้ค่านั้น
        if val and val.strip() != "":
            return float(val)
    except:
        pass
    # ถ้าไม่มีจริงๆ ค่อยใช้ค่า Default (แต่วิธีใหม่นี้จะมีค่าเสมอ)
    return default_val

# --- 🎯 UPDATED CONFIG: แยกค่า RSI Trigger ของใครของมัน ---
PORTFOLIO_HOLDINGS = {
    'QQQM': {
        'qty': get_config('INPUT_QQQM_QTY', 0.0), 
        'avg_cost': get_config('INPUT_QQQM_COST', 0.0),
        'rsi_trigger': 50
    },
    'SMH': {
        'qty': get_config('INPUT_SMH_QTY', 0.0), 
        'avg_cost': get_config('INPUT_SMH_COST', 0.0),
        'rsi_trigger': 45  # ⚡ SMH ผันผวนกว่า รอให้ย่อลึกกว่า QQQM นิดนึง (45) ค่อยยิง
    },
    'CASH': get_config('INPUT_CASH_BALANCE', 175.04)
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

print(f"🔄 System Running... Advanced Sniper Mode Activated")
total_port_value = PORTFOLIO_HOLDINGS['CASH']
msg_body = ""
signals = []

for ticker in ['QQQM', 'SMH']:
    try:
        t_data = yf.Ticker(ticker)
        df = t_data.history(period="1y")
        
        latest_price = df['Close'].iloc[-1]
        rsi = calculate_rsi(df['Close']).iloc[-1]
        sma120 = df['Close'].rolling(window=120).mean().iloc[-1]
        
        # ดึง RSI Trigger เฉพาะของหุ้นตัวนั้นๆ
        target_rsi = PORTFOLIO_HOLDINGS[ticker]['rsi_trigger']

        next_div = "N/A"
        try:
            div_history = t_data.dividends
            if not div_history.empty: next_div = div_history.index[-1].strftime('%Y-%m-%d')
        except: pass

        news_text = ""
        try:
            news = t_data.news
            if news: news_text = f"📰 News: *{news[0]['title']}*"
        except: pass

        is_uptrend = latest_price > sma120
        # ใช้ค่า RSI ที่แยกกันของแต่ละตัวมาเช็ก
        is_oversold = rsi < target_rsi 
        
        action_msg = ""
        if is_uptrend and is_oversold:
            action_msg = f"\n🚨 **BUY SIGNAL!** (RSI < {target_rsi})"
            signals.append(ticker)
        elif not is_uptrend:
            action_msg = "\n⚠️ *Warning: Down Trend*"
        
        qty = PORTFOLIO_HOLDINGS[ticker]['qty']
        cost = PORTFOLIO_HOLDINGS[ticker]['avg_cost']
        current_val = latest_price * qty
        pl_pct = ((latest_price - cost) / cost) * 100
        total_port_value += current_val

        trend_icon = "🟢" if is_uptrend else "🔴"
        
        msg_body += f"**💎 {ticker}**\n"
        msg_body += f"Price: `${latest_price:.2f}` ({trend_icon} UP)\n"
        # แสดงค่า RSI Target ในวงเล็บให้เห็นชัดๆ
        msg_body += f"RSI: `{rsi:.1f}` (Target < {target_rsi}) | Div: `{next_div}`\n"
        msg_body += f"P/L: `{pl_pct:+.2f}%` \n"
        msg_body += f"(Cost: `${cost:.2f}` | Qty: `{qty}`){action_msg}\n"
        if news_text: msg_body += f"{news_text}\n"
        msg_body += "\n"

    except Exception as e: print(f"❌ Error {ticker}: {e}")

header = f"🤖 **ENGINEER BOT REPORT**\n📅 {datetime.date.today()}\n"
if signals: header = f"🔥 **SNIPER ALERT!** 🔥\n" + header
summary = f"💰 **Wealth:** `${total_port_value:.2f}`\n💵 **Buffer:** `${PORTFOLIO_HOLDINGS['CASH']:.2f}`"
alert = "\n\n⚠️ **REFILL CASH** (<$100)" if PORTFOLIO_HOLDINGS['CASH'] < 100 else ""

send_discord_alert(header + "-"*20 + "\n" + msg_body + "-"*20 + "\n" + summary + alert)
