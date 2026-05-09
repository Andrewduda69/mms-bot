import requests
import pandas as pd
import numpy as np
import time

BOT_TOKEN = "8409956991:AAHtQm-3YY09DLjIGoTSqudtMd_wgq_d2FM"
CHAT_ID = "-5299312717"

def send_telegram(msg):
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": msg}
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

# Stan pozycji
active_direction = None
active_sl = None
active_tp = None
active_entry = None

send_telegram("MMS Bot uruchomiony! Monitoruje BTCUSDT M15...")

while True:
    try:
        df = get_bybit_klines()

        tma_mid = tma(df["close"], 240)
        atr_val = atr(df, 14)
        upper = tma_mid + 1.5 * atr_val
        lower = tma_mid - 1.5 * atr_val
        stoch_k = stochastic(df)

        i = len(df) - 2
        current_high = df["high"].iloc[-1]
        current_low = df["low"].iloc[-1]

        touched_upper = df["high"].iloc[i] >= upper.iloc[i]
        touched_lower = df["low"].iloc[i] <= lower.iloc[i]
        bear_reaction = df["close"].iloc[i] < df["open"].iloc[i]
        bull_reaction = df["close"].iloc[i] > df["open"].iloc[i]
        stoch_ob = stoch_k.iloc[i] >= 70
        stoch_os = stoch_k.iloc[i] <= 30

        ts = pd.Timestamp(df["time"].iloc[i] * 1000000)
        hour = ts.hour
        weekday = ts.weekday()
        time_ok = weekday not in [5, 6]

        signal_long = touched_lower and bull_reaction and stoch_os and time_ok
        signal_short = touched_upper and bear_reaction and stoch_ob and time_ok

        close_price = df["close"].iloc[i]
        sl_long = round(close_price * (1 - 0.019), 0)
        tp_long = round(upper.iloc[i], 0)
        sl_short = round(close_price * (1 + 0.019), 0)
        tp_short = round(lower.iloc[i], 0)

        rr_long = round(abs(tp_long - close_price) / abs(close_price - sl_long), 2)
        rr_short = round(abs(close_price - tp_short) / abs(sl_short - close_price), 2)

        # Sprawdz TP/SL dla aktywnej pozycji
        if active_direction == "LONG" and active_sl and active_tp:
            if current_low <= active_sl:
                send_telegram(f"SL trafiony! LONG zamkniety na {active_sl}")
                active_direction = None
                active_sl = None
                active_tp = None
                active_entry = None
            elif current_high >= active_tp:
                send_telegram(f"TP trafiony! LONG zamkniety na {active_tp}")
                active_direction = None
                active_sl = None
                active_tp = None
                active_entry = None

        elif active_direction == "SHORT" and active_sl and active_tp:
            if current_high >= active_sl:
                send_telegram(f"SL trafiony! SHORT zamkniety na {active_sl}")
                active_direction = None
                active_sl = None
                active_tp = None
                active_entry = None
            elif current_low <= active_tp:
                send_telegram(f"TP trafiony! SHORT zamkniety na {active_tp}")
                active_direction = None
                active_sl = None
                active_tp = None
                active_entry = None

        # Nowy sygnal tylko gdy brak aktywnej pozycji lub przeciwny kierunek
        if signal_long and active_direction != "LONG":
            if active_direction == "SHORT":
                send_telegram(f"Zamknij SHORT! Nowy sygnal LONG.")
            rr_ok = "OK" if rr_long >= 1.5 else "SLABY"
            send_telegram(f"LONG!\nEntry: {close_price}\nSL: {sl_long}\nTP: {tp_long}\nRR: {rr_long} {rr_ok}\nStoch: {round(stoch_k.iloc[i],1)}")
            active_direction = "LONG"
            active_sl = sl_long
            active_tp = tp_long
            active_entry = close_price

        elif signal_short and active_direction != "SHORT":
            if active_direction == "LONG":
                send_telegram(f"Zamknij LONG! Nowy sygnal SHORT.")
            rr_ok = "OK" if rr_short >= 1.5 else "SLABY"
            send_telegram(f"SHORT!\nEntry: {close_price}\nSL: {sl_short}\nTP: {tp_short}\nRR: {rr_short} {rr_ok}\nStoch: {round(stoch_k.iloc[i],1)}")
            active_direction = "SHORT"
            active_sl = sl_short
            active_tp = tp_short
            active_entry = close_price

        time.sleep(60)

    except Exception as e:
        send_telegram(f"Blad bota: {str(e)}")
        time.sleep(60)
