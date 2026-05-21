import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timezone

BOT_TOKEN = "8409956991:AAHtQm-3YY09DLjIGoTSqudtMd_wgq_d2FM"
CHAT_ID = "-5299312717"

MACRO_EVENTS = []

def send_telegram(msg):
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": msg}
    )

def get_klines(interval="15m", limit=500):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
    r = requests.get(url, params=params)
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "time","open","high","low","close","volume",
        "close_time","quote_volume","trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ])
    df = df[["time","open","high","low","close","volume"]]
    df = df.astype(float)
    return df

def tma(series, length):
    sma1 = series.rolling(length).mean()
    return sma1.rolling(length).mean()

def atr_calc(df, length=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()

def stochastic_kd(df, k=14, smooth_k=3, smooth_d=3):
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    stoch = 100 * (df["close"] - low_min) / (high_max - low_min)
    stoch_k = stoch.rolling(smooth_k).mean()
    stoch_d = stoch_k.rolling(smooth_d).mean()
    return stoch_k, stoch_d

def calc_adx(df, length=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    plus_dm = high.diff()
    minus_dm = low.diff().abs()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(length).mean()
    plus_di = 100 * (plus_dm.rolling(length).mean() / atr14)
    minus_di = 100 * (minus_dm.rolling(length).mean() / atr14)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.rolling(length).mean()
    return adx

def is_macro_blackout():
    now = datetime.now(timezone.utc)
    for date_str, hour in MACRO_EVENTS:
        event_dt = datetime.strptime(f"{date_str} {hour}:00", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        diff = abs((now - event_dt).total_seconds() / 3600)
        if diff <= 2:
            return True
    return False

active_direction = None
pending_signal   = None
pending_sl       = None
pending_qty      = None
last_close_time  = None
COOLDOWN_MINUTES = 30

send_telegram("MMS Bot v16 — Prosty, czysty, działa!")

while True:
    try:
        df    = get_klines("15m", 500)
        df_h1 = get_klines("1h", 100)

        tma_mid = tma(df["close"], 240)
        atr_val = atr_calc(df, 14)
        upper   = tma_mid + 1.5 * atr_val
        lower   = tma_mid - 1.5 * atr_val

        stoch_k_m15, _ = stochastic_kd(df)
        stoch_ob = stoch_k_m15.iloc[-2] >= 70
        stoch_os = stoch_k_m15.iloc[-2] <= 30

        stoch_k_h1, stoch_d_h1 = stochastic_kd(df_h1)
        h1_k      = stoch_k_h1.iloc[-2]
        h1_d      = stoch_d_h1.iloc[-2]
        h1_k_prev = stoch_k_h1.iloc[-3]
        h1_d_prev = stoch_d_h1.iloc[-3]

        h1_cross_up   = h1_k_prev < h1_d_prev and h1_k > h1_d
        h1_cross_down = h1_k_prev > h1_d_prev and h1_k < h1_d

        adx    = calc_adx(df, 14)
        adx_val = adx.iloc[-2]
        adx_ok  = adx_val < 40

        i             = len(df) - 2
        current_price = df["close"].iloc[-1]

        touched_upper = df["high"].iloc[i] >= upper.iloc[i]
        touched_lower = df["low"].iloc[i] <= lower.iloc[i]
        bear_reaction = df["close"].iloc[i] < df["open"].iloc[i]
        bull_reaction = df["close"].iloc[i] > df["open"].iloc[i]

        ts         = pd.Timestamp(df["time"].iloc[i] * 1000000)
        weekday    = ts.weekday()
        no_weekend = weekday not in [5, 6]

        hour_utc        = ts.hour
        us_session      = 15 <= hour_utc < 17
        us_session_info = "🇺🇸 Sesja US aktywna!" if us_session else ""

        momentum          = (df["close"].iloc[i] - df["close"].iloc[i-3]) / df["close"].iloc[i-3] * 100
        momentum_ok_long  = momentum > -1.5
        momentum_ok_short = momentum < 1.5

        macro_block = is_macro_blackout()

        h4_start = ts.minute < 15 and ts.hour % 4 == 0

        close_price      = df["close"].iloc[i]
        current_tma_mid  = round(tma_mid.iloc[-1], 0)
        sl_long          = round(close_price * (1 - 0.019), 0)
        sl_short         = round(close_price * (1 + 0.019), 0)
        tp_long          = round(upper.iloc[i], 0)
        tp_short         = round(lower.iloc[i], 0)
        qty              = round(375 / abs(close_price * 0.019), 4)

        rr_long  = round(abs(tp_long - close_price) / abs(close_price - sl_long), 2)
        rr_short = round(abs(close_price - tp_short) / abs(sl_short - close_price), 2)

        if adx_val < 25:
            adx_info = f"ADX: {round(adx_val,1)} ✅ OK"
        elif adx_val < 40:
            adx_info = f"ADX: {round(adx_val,1)} ⚠️ UWAGA"
        else:
            adx_info = f"ADX: {round(adx_val,1)} ❌ TREND"

        if h1_cross_up:
            h1_cross_info = " 📈 CROSS UP"
        elif h1_cross_down:
            h1_cross_info = " 📉 CROSS DOWN"
        else:
            h1_cross_info = ""

        if h1_k <= 30:
            h1_info = f"H1 Stoch: {round(h1_k,1)} 🟢 OS{h1_cross_info}"
        elif h1_k >= 70:
            h1_info = f"H1 Stoch: {round(h1_k,1)} 🔴 OB{h1_cross_info}"
        else:
            h1_info = f"H1 Stoch: {round(h1_k,1)} ⚪ Neutral{h1_cross_info}"

        # Cooldown
        in_cooldown = False
        if last_close_time:
            elapsed = (datetime.now(timezone.utc) - last_close_time).total_seconds() / 60
            if elapsed < COOLDOWN_MINUTES:
                in_cooldown = True

        signal_long  = (touched_lower and bull_reaction and stoch_os and
                       no_weekend and momentum_ok_long and not macro_block and adx_ok and not in_cooldown)

        signal_short = (touched_upper and bear_reaction and stoch_ob and
                       no_weekend and momentum_ok_short and not macro_block and adx_ok and not in_cooldown)

        # Kampania H4
        if h4_start and active_direction == "LONG" and momentum < -1.0:
            send_telegram(
                f"⚠️ KAMPANIA H4 PODAZOWA!\n"
                f"Momentum: {round(momentum,2)}%\n"
                f"Rozważ zamknięcie LONG!"
            )

        if h4_start and active_direction == "SHORT" and momentum > 1.0:
            send_telegram(
                f"⚠️ KAMPANIA H4 POPYTOWA!\n"
                f"Momentum: {round(momentum,2)}%\n"
                f"Rozważ zamknięcie SHORT!"
            )

        # Pending
        if active_direction is None and not in_cooldown:
            if signal_long and pending_signal != "LONG":
                pending_signal = "LONG"
                pending_sl     = sl_long
                pending_qty    = qty
                send_telegram(
                    f"⏳ OCZEKUJE na potwierdzenie LONG\n"
                    f"Następna świeca musi być zielona\n"
                    f"Strefa: {close_price}\n"
                    f"SL: {sl_long}\n"
                    f"TP min (TMA Mid): {current_tma_mid}\n"
                    f"TP max (pasmo): {tp_long}"
                )

            elif signal_short and pending_signal != "SHORT":
                pending_signal = "SHORT"
                pending_sl     = sl_short
                pending_qty    = qty
                send_telegram(
                    f"⏳ OCZEKUJE na potwierdzenie SHORT\n"
                    f"Następna świeca musi być czerwona\n"
                    f"Strefa: {close_price}\n"
                    f"SL: {sl_short}\n"
                    f"TP min (TMA Mid): {current_tma_mid}\n"
                    f"TP max (pasmo): {tp_short}"
                )

        # Potwierdzenie świecy
        if pending_signal == "LONG" and bull_reaction and active_direction is None:
            send_telegram(
                f"🟢 LONG! ✅ Świeca potwierdzona\n"
                f"Entry: {close_price}\n"
                f"SL: {pending_sl}\n"
                f"TP min: {current_tma_mid} (TMA Mid)\n"
                f"TP max: {tp_long} (pasmo)\n"
                f"RR min: {rr_long}\n"
                f"Qty: {pending_qty} BTC\n"
                f"Stoch M15: {round(stoch_k_m15.iloc[i],1)}\n"
                f"{h1_info}\n"
                f"{adx_info}\n"
                f"Momentum: {round(momentum,2)}%\n"
                f"{us_session_info}"
            )
            active_direction = "LONG"
            pending_signal   = None
            pending_sl       = None
            pending_qty      = None

        elif pending_signal == "SHORT" and bear_reaction and active_direction is None:
            send_telegram(
                f"🔴 SHORT! ✅ Świeca potwierdzona\n"
                f"Entry: {close_price}\n"
                f"SL: {pending_sl}\n"
                f"TP min: {current_tma_mid} (TMA Mid)\n"
                f"TP max: {tp_short} (pasmo)\n"
                f"RR min: {rr_short}\n"
                f"Qty: {pending_qty} BTC\n"
                f"Stoch M15: {round(stoch_k_m15.iloc[i],1)}\n"
                f"{h1_info}\n"
                f"{adx_info}\n"
                f"Momentum: {round(momentum,2)}%\n"
                f"{us_session_info}"
            )
            active_direction = "SHORT"
            pending_signal   = None
            pending_sl       = None
            pending_qty      = None

        elif pending_signal and not bull_reaction and not bear_reaction:
            send_telegram(f"❌ Sygnał {pending_signal} nie potwierdzony — pomijam.")
            pending_signal = None
            pending_sl     = None
            pending_qty    = None

        time.sleep(120)

    except Exception as e:
        send_telegram(f"Blad bota: {str(e)}")
        time.sleep(120)
