import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timezone

BOT_TOKEN = "8409956991:AAHtQm-3YY09DLjIGoTSqudtMd_wgq_d2FM"
CHAT_ID = "-5299312717"

# Kalendarz makro - daty i godziny UTC gdy nie handlujemy
# Format: ("YYYY-MM-DD", HH) - blokada 2h przed i po
MACRO_EVENTS = []

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

def is_macro_blackout():
    now = datetime.now(timezone.utc)
    for date_str, hour in MACRO_EVENTS:
        event_dt = datetime.strptime(f"{date_str} {hour}:00", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        diff = abs((now - event_dt).total_seconds() / 3600)
        if diff <= 2:
            return True
    return False

def check_momentum(df):
    # Sprawdź czy ostatnie 3 świece M15 to silny trend
    i = len(df) - 2
    change_3 = (df["close"].iloc[i] - df["close"].iloc[i-3]) / df["close"].iloc[i-3] * 100
    return change_3  # ujemne = spadek, dodatnie = wzrost

# Stan pozycji
active_direction = None
active_sl = None
active_tp = None
active_entry = None
tp_alert_sent = False

send_telegram("MMS Bot v2 uruchomiony! Monitoruje BTCUSDT M15...")

while True:
    try:
        df = get_bybit_klines()

        tma_mid = tma(df["close"], 240)
        atr_val = atr(df, 14)
        upper = tma_mid + 1.5 * atr_val
        lower = tma_mid - 1.5 * atr_val
        stoch_k = stochastic(df)

        i = len(df) - 2
        current_price = df["close"].iloc[-1]
        current_high = df["high"].iloc[-1]
        current_low = df["low"].iloc[-1]

        touched_upper = df["high"].iloc[i] >= upper.iloc[i]
        touched_lower = df["low"].iloc[i] <= lower.iloc[i]
        bear_reaction = df["close"].iloc[i] < df["open"].iloc[i]
        bull_reaction = df["close"].iloc[i] > df["open"].iloc[i]
        stoch_ob = stoch_k.iloc[i] >= 70
        stoch_os = stoch_k.iloc[i] <= 30

        ts = pd.Timestamp(df["time"].iloc[i] * 1000000)
        weekday = ts.weekday()
        no_weekend = weekday not in [5, 6]

        momentum = check_momentum(df)
        macro_block = is_macro_blackout()

        # Filtr momentum - blokuj LONG gdy silny spadek (>1.5% w 3 świecach)
        momentum_ok_long = momentum > -1.5
        # Blokuj SHORT gdy silny wzrost (>1.5% w 3 świecach)
        momentum_ok_short = momentum < 1.5

        signal_long = touched_lower and bull_reaction and stoch_os and no_weekend and momentum_ok_long and not macro_block
        signal_short = touched_upper and bear_reaction and stoch_ob and no_weekend and momentum_ok_short and not macro_block

        close_price = df["close"].iloc[i]
        sl_long = round(close_price * (1 - 0.019), 0)
        tp_long = round(upper.iloc[i], 0)
        sl_short = round(close_price * (1 + 0.019), 0)
        tp_short = round(lower.iloc[i], 0)

        # RR obliczenie
        rr_long = round(abs(tp_long - close_price) / abs(close_price - sl_long), 2)
        rr_short = round(abs(close_price - tp_short) / abs(sl_short - close_price), 2)

        # Qty sugerowane
        risk_usd = 375
        qty_long = round(risk_usd / abs(close_price - sl_long), 4)
        qty_short = round(risk_usd / abs(sl_short - close_price), 4)

        # Sprawdź TP/SL dla aktywnej pozycji
        if active_direction == "LONG" and active_sl and active_tp:
            # Alert blisko TP
            dist_to_tp = abs(active_tp - current_price) / abs(active_tp - active_entry) * 100
            if dist_to_tp <= 15 and not tp_alert_sent:
                send_telegram(
                    f"⚠️ BLISKO TP! Rozważ SL na BE!\n"
                    f"Cena: {current_price}\n"
                    f"TP: {active_tp} (zostało {round(dist_to_tp,1)}%)\n"
                    f"Przesuń SL na: {active_entry}"
                )
                tp_alert_sent = True

            if current_low <= active_sl:
                send_telegram(f"❌ SL trafiony! LONG zamkniety na {active_sl}")
                active_direction = None
                active_sl = None
                active_tp = None
                active_entry = None
                tp_alert_sent = False
            elif current_high >= active_tp:
                send_telegram(f"✅ TP trafiony! LONG zamkniety na {active_tp}")
                active_direction = None
                active_sl = None
                active_tp = None
                active_entry = None
                tp_alert_sent = False

        elif active_direction == "SHORT" and active_sl and active_tp:
            # Alert blisko TP
            dist_to_tp = abs(current_price - active_tp) / abs(active_entry - active_tp) * 100
            if dist_to_tp <= 15 and not tp_alert_sent:
                send_telegram(
                    f"⚠️ BLISKO TP! Rozważ SL na BE!\n"
                    f"Cena: {current_price}\n"
                    f"TP: {active_tp} (zostało {round(dist_to_tp,1)}%)\n"
                    f"Przesuń SL na: {active_entry}"
                )
                tp_alert_sent = True

            if current_high >= active_sl:
                send_telegram(f"❌ SL trafiony! SHORT zamkniety na {active_sl}")
                active_direction = None
                active_sl = None
                active_tp = None
                active_entry = None
                tp_alert_sent = False
            elif current_low <= active_tp:
                send_telegram(f"✅ TP trafiony! SHORT zamkniety na {active_tp}")
                active_direction = None
                active_sl = None
                active_tp = None
                active_entry = None
                tp_alert_sent = False

        # Nowe sygnały
        if signal_long and active_direction != "LONG":
            if macro_block:
                send_telegram("⛔ LONG zablokowany - dane makro!")
            else:
                if active_direction == "SHORT":
                    send_telegram("🔄 Zamknij SHORT! Nowy sygnał LONG.")
                rr_txt = "OK" if rr_long >= 1.0 else "SLABY"
                send_telegram(
                    f"🟢 LONG!\n"
                    f"Entry: {close_price}\n"
                    f"SL: {sl_long}\n"
                    f"TP: {tp_long}\n"
                    f"RR: {rr_long} {rr_txt}\n"
                    f"Qty: {qty_long} BTC\n"
                    f"Stoch: {round(stoch_k.iloc[i],1)}\n"
                    f"Momentum: {round(momentum,2)}%"
                )
                active_direction = "LONG"
                active_sl = sl_long
                active_tp = tp_long
                active_entry = close_price
                tp_alert_sent = False

        elif signal_short and active_direction != "SHORT":
            if macro_block:
                send_telegram("⛔ SHORT zablokowany - dane makro!")
            else:
                if active_direction == "LONG":
                    send_telegram("🔄 Zamknij LONG! Nowy sygnał SHORT.")
                rr_txt = "OK" if rr_short >= 1.0 else "SLABY"
                send_telegram(
                    f"🔴 SHORT!\n"
                    f"Entry: {close_price}\n"
                    f"SL: {sl_short}\n"
                    f"TP: {tp_short}\n"
                    f"RR: {rr_short} {rr_txt}\n"
                    f"Qty: {qty_short} BTC\n"
                    f"Stoch: {round(stoch_k.iloc[i],1)}\n"
                    f"Momentum: {round(momentum,2)}%"
                )
                active_direction = "SHORT"
                active_sl = sl_short
                active_tp = tp_short
                active_entry = close_price
                tp_alert_sent = False

        time.sleep(120)

    except Exception as e:
        send_telegram(f"Blad bota: {str(e)}")
        time.sleep(120)
