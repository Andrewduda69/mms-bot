import requests
import pandas as pd
import numpy as np
import time

BOT_TOKEN = "8409956991:AAHtQm-3YY09DLjIGoTSqudtMd_wgq_d2FM"
CHAT_ID = "-5299312717"

def send_telegram(msg):
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    )

def get_bybit_klines():
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": "BTCUSDT",
        "interval": "15",
        "limit": 500
    }
    r = requests.get(url, params=params)
    resp = r.json()
    if resp.get("retCode") != 0:
        raise Exception(f"Bybit error: {resp}")
    data = resp["result"]["list"]
    df = pd.DataFrame(data, columns=["time","open","high","low","close","volume","turnover"])
    df = df.astype(float)
    df = df.iloc[::-1].reset_index(drop=True)
    return df

def tma(series, length):
    sma1 = series.rolling(length).mean()
    return sma1.rolling(length).mean()

def atr(df, length=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()

def stochastic(df, k=14, smooth=3):
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    stoch = 100 * (df["close"] - low_min) / (high_max - low_min)
    return stoch.rolling(smooth).mean()

last_signal = None

send_telegram("✅ MMS Bot uruchomiony! Monitoruję BTCUSDT M15...")

while True:
    try:
        df = get_bybit_klines()

        tma_mid = tma(df["close"], 240)
        atr_val = atr(df, 14)
        upper = tma_mid + 1.2 * atr_val
        lower = tma_mid - 1.2 * atr_val
        stoch_k = stochastic(df)

        i = len(df) - 2

        touched_upper = df["high"].iloc[i] >= upper.iloc[i]
        touched_lower = df["low"].iloc[i] <= lower.iloc[i]
        bear_reaction = df["close"].iloc[i] < df["open"].iloc[i]
        bull_reaction = df["close"].iloc[i] > df["open"].iloc[i]
        stoch_ob = stoch_k.iloc[i] >= 70
        stoch_os = stoch_k.iloc[i] <= 30

        ts = pd.Timestamp(df["time"].iloc[i] * 1000000)
        hour = ts.hour
        weekday = ts.weekday()
        time_ok = 8 <= hour < 20 and weekday in [1, 2, 3]

        signal_long = touched_lower and bull_reaction and stoch_os and time_ok
        signal_short = touched_upper and bear_reaction and stoch_ob and time_ok

        close_price = df["close"].iloc[i]
        sl_long = round(close_price * (1 - 0.019), 0)
        tp_long = round(upper.iloc[i], 0)
        sl_short = round(close_price * (1 + 0.019), 0)
        tp_short = round(lower.iloc[i], 0)

        if signal_long:
            msg = f"🟢 LONG!\nEntry: {close_price}\nSL: {sl_long}\nTP: {tp_long}\nStoch: {round(stoch_k.iloc[i],1)}"
        elif signal_short:
            msg = f"🔴 SHORT!\nEntry: {close_price}\nSL: {sl_short}\nTP: {tp_short}\nStoch: {round(stoch_k.iloc[i],1)}"
        else:
            msg = None

        if msg and msg != last_signal:
            send_telegram(msg)
            last_signal = msg

        time.sleep(60)

    except Exception as e:
        send_telegram(f"Blad bota: {str(e)}")
        time.sleep(60)
