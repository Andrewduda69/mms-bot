import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timezone, date

BOT_TOKEN = "8409956991:AAHtQm-3YY09DLjIGoTSqudtMd_wgq_d2FM"
CHAT_ID = "-5299312717"

MACRO_EVENTS = []

state = {
    "direction":     None,
    "entry":         None,
    "size_mult":     1.0,
    "base_bar":      None,
    "dokladka_done": False,
    "pending":       None,
    "pending_bar":   None,
}

last_update_id = 0

def send_telegram(msg):
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": msg}
    )

def get_updates():
    global last_update_id
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 1},
            timeout=5
        )
        for update in r.json().get("result", []):
            last_update_id = update["update_id"]
            msg = update.get("message", {}).get("text", "")
            if msg.strip() == "/reset":
                for k in state:
                    state[k] = None
                state["size_mult"]     = 1.0
                state["dokladka_done"] = False
                send_telegram("✅ Reset — bot gotowy.")
            elif msg.strip() == "/sl01":
                state["size_mult"] = 0.1
                send_telegram("⚠️ Sekwencyjność x0.1 — po SL.")
            elif msg.strip() == "/sl1":
                state["size_mult"] = 1.0
                send_telegram("✅ Sekwencyjność x1 — po zysku.")
            elif msg.strip() == "/status":
                send_telegram(
                    f"📊 Status:\n"
                    f"Pozycja: {state['direction'] or 'Brak'}\n"
                    f"Entry: {state['entry'] or '-'}\n"
                    f"Size: x{state['size_mult']}\n"
                    f"Dokładka: {'TAK' if state['dokladka_done'] else 'NIE'}\n"
                    f"Pending: {state['pending'] or 'Brak'}"
                )
    except:
        pass

def get_klines(interval="15m", limit=500):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
    r = requests.get(url, params=params)
    df = pd.DataFrame(r.json(), columns=[
        "time","open","high","low","close","volume",
        "close_time","quote_volume","trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ])
    df = df[["time","open","high","low","close","volume"]].astype(float)
    return df

def tma(series, length):
    sma1 = series.rolling(length).mean()
    return sma1.rolling(length).mean()

def atr_calc(df, length=14):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()

def stochastic(df, k=14, smooth=3):
    low_min  = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    stoch    = 100 * (df["close"] - low_min) / (high_max - low_min)
    return stoch.rolling(smooth).mean()

def is_macro_blackout():
    now = datetime.now(timezone.utc)
    for date_str, hour in MACRO_EVENTS:
        event_dt = datetime.strptime(
            f"{date_str} {hour}:00", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)
        if abs((now - event_dt).total_seconds() / 3600) <= 2:
            return True
    return False

def get_h4_campaign():
    df_h4  = get_klines("4h", 10)
    h4_chg = (df_h4["close"].iloc[-2] - df_h4["open"].iloc[-2]) / df_h4["open"].iloc[-2] * 100
    if h4_chg < -0.3:
        return "BEARISH"
    elif h4_chg > 0.3:
        return "BULLISH"
    return "NEUTRAL"

def qty(price, mult=1.0):
    risk = 25000 * 1.0 / 100
    return round(risk / (price * 0.02) * mult, 4)

def qty_dok(price):
    risk = 25000 * 1.0 / 100
    return round(risk / (price * 0.01), 4)

send_telegram("MMS Bot v21 — uruchomiony!")

parametryzacja_wyslana = set()

while True:
    try:
        get_updates()

        df = get_klines("15m", 500)

        tma_mid = tma(df["close"], 240)
        atr_val = atr_calc(df, 14)
        upper   = tma_mid + 1.5 * atr_val
        lower   = tma_mid - 1.5 * atr_val
        stoch   = stochastic(df)

        i             = len(df) - 2
        current_bar   = i
        close_price   = df["close"].iloc[i]

        bull_reaction = df["close"].iloc[i] > df["open"].iloc[i]
        bear_reaction = df["close"].iloc[i] < df["open"].iloc[i]

        touched_lower = df["low"].iloc[i]  <= lower.iloc[i]
        touched_upper = df["high"].iloc[i] >= upper.iloc[i]

        is_os = stoch.iloc[i] <= 20
        is_ob = stoch.iloc[i] >= 80

        ts         = pd.Timestamp(df["time"].iloc[i] * 1000000)
        is_weekend = ts.weekday() in [5, 6]
        macro_ok   = not is_macro_blackout()

        h4_campaign       = get_h4_campaign()
        camp_blocks_long  = h4_campaign == "BEARISH"
        camp_blocks_short = h4_campaign == "BULLISH"

        sl_long  = round(close_price * 0.98, 0)
        sl_short = round(close_price * 1.02, 0)
        tp_long  = round(upper.iloc[i], 0)
        tp_short = round(lower.iloc[i], 0)
        size     = qty(close_price, state["size_mult"])
        size_d   = qty_dok(close_price)

        hour_utc        = ts.hour
        us_session      = 15 <= hour_utc < 17
        us_session_info = "🇺🇸 US aktywna!" if us_session else ""

        if stoch.iloc[i] <= 20:
            stoch_info = f"Stoch: {round(stoch.iloc[i],1)} 🟢 OS"
        elif stoch.iloc[i] >= 80:
            stoch_info = f"Stoch: {round(stoch.iloc[i],1)} 🔴 OB"
        else:
            stoch_info = f"Stoch: {round(stoch.iloc[i],1)} ⚪ Neutral"

        camp_info = f"H4: {h4_campaign}"

        signal_long  = (touched_lower and bull_reaction and is_os and
                        not is_weekend and macro_ok and not camp_blocks_long)

        signal_short = (touched_upper and bear_reaction and is_ob and
                        not is_weekend and macro_ok and not camp_blocks_short)

        # ─── PENDING ──────────────────────────────────────────
        if state["direction"] is None and state["pending"] is None:
            if signal_long:
                state["pending"]     = "LONG"
                state["pending_bar"] = current_bar
                send_telegram(
                    f"⏳ OCZEKUJE LONG\n"
                    f"Następna świeca musi być zielona\n"
                    f"Strefa: {close_price}\n"
                    f"SL: {sl_long} | TP: {tp_long}\n"
                    f"{stoch_info} | {camp_info}"
                )
            elif signal_short:
                state["pending"]     = "SHORT"
                state["pending_bar"] = current_bar
                send_telegram(
                    f"⏳ OCZEKUJE SHORT\n"
                    f"Następna świeca musi być czerwona\n"
                    f"Strefa: {close_price}\n"
                    f"SL: {sl_short} | TP: {tp_short}\n"
                    f"{stoch_info} | {camp_info}"
                )

        # ─── POTWIERDZENIE ŚWIECY ─────────────────────────────
        if state["pending"] == "LONG" and current_bar == state["pending_bar"] + 1:
            if bull_reaction:
                send_telegram(
                    f"🟢 LONG! ✅\n"
                    f"Entry: {close_price}\n"
                    f"SL: {sl_long} (2%)\n"
                    f"TP: {tp_long}\n"
                    f"Size: {size} BTC\n"
                    f"{stoch_info} | {camp_info}\n"
                    f"{us_session_info}\n"
                    f"Po zamknięciu → /reset"
                )
                state["direction"]     = "LONG"
                state["entry"]         = close_price
                state["base_bar"]      = current_bar
                state["dokladka_done"] = False
            state["pending"]     = None
            state["pending_bar"] = None

        elif state["pending"] == "SHORT" and current_bar == state["pending_bar"] + 1:
            if bear_reaction:
                send_telegram(
                    f"🔴 SHORT! ✅\n"
                    f"Entry: {close_price}\n"
                    f"SL: {sl_short} (2%)\n"
                    f"TP: {tp_short}\n"
                    f"Size: {size} BTC\n"
                    f"{stoch_info} | {camp_info}\n"
                    f"{us_session_info}\n"
                    f"Po zamknięciu → /reset"
                )
                state["direction"]     = "SHORT"
                state["entry"]         = close_price
                state["base_bar"]      = current_bar
                state["dokladka_done"] = False
            state["pending"]     = None
            state["pending_bar"] = None

        # ─── DOKŁADKA ─────────────────────────────────────────
        if (state["direction"] == "LONG" and
            not state["dokladka_done"] and
            state["base_bar"] is not None and
            current_bar == state["base_bar"] + 1 and
            bull_reaction):
            send_telegram(
                f"⚡ DOKŁADKA LONG\n"
                f"Entry: {close_price}\n"
                f"SL knot: {round(df['low'].iloc[i], 0)}\n"
                f"Size: {size_d} BTC\n"
                f"Max SL dokładki 1%: {round(close_price * 0.99, 0)}"
            )
            state["dokladka_done"] = True

        if (state["direction"] == "SHORT" and
            not state["dokladka_done"] and
            state["base_bar"] is not None and
            current_bar == state["base_bar"] + 1 and
            bear_reaction):
            send_telegram(
                f"⚡ DOKŁADKA SHORT\n"
                f"Entry: {close_price}\n"
                f"SL knot: {round(df['high'].iloc[i], 0)}\n"
                f"Size: {size_d} BTC\n"
                f"Max SL dokładki 1%: {round(close_price * 1.01, 0)}"
            )
            state["dokladka_done"] = True

        # ─── CUT AND REVERSE ──────────────────────────────────
        if state["direction"] == "LONG":
            if touched_upper and bear_reaction and is_ob and not camp_blocks_short:
                send_telegram(
                    f"🔄 CUT AND REVERSE!\n"
                    f"Zamknij LONG → Otwórz SHORT\n"
                    f"Entry SHORT: {close_price}\n"
                    f"SL: {sl_short} (2%)\n"
                    f"TP: {tp_short}\n"
                    f"Size: {size} BTC\n"
                    f"Po zamknięciu → /reset gdy wyjdziesz"
                )
                state["direction"]     = "SHORT"
                state["entry"]         = close_price
                state["base_bar"]      = current_bar
                state["dokladka_done"] = False
                state["pending"]       = None

        elif state["direction"] == "SHORT":
            if touched_lower and bull_reaction and is_os and not camp_blocks_long:
                send_telegram(
                    f"🔄 CUT AND REVERSE!\n"
                    f"Zamknij SHORT → Otwórz LONG\n"
                    f"Entry LONG: {close_price}\n"
                    f"SL: {sl_long} (2%)\n"
                    f"TP: {tp_long}\n"
                    f"Size: {size} BTC\n"
                    f"Po zamknięciu → /reset gdy wyjdziesz"
                )
                state["direction"]     = "LONG"
                state["entry"]         = close_price
                state["base_bar"]      = current_bar
                state["dokladka_done"] = False
                state["pending"]       = None

        # ─── PRZYPOMNIENIE PARAMETRYZACJI ─────────────────────
        today = date.today()
        klucz = (today.year, today.month, today.day)
        if today.day in [1, 16] and klucz not in parametryzacja_wyslana:
            send_telegram(
                "🔔 CZAS NA PARAMETRYZACJĘ!\n"
                "Uruchom optimizer.py na komputerze:\n"
                "py C:\\Users\\Lucas\\Desktop\\optimizer.py"
            )
            parametryzacja_wyslana.add(klucz)

        time.sleep(120)

    except Exception as e:
        send_telegram(f"Błąd bota: {str(e)}")
        time.sleep(120)
