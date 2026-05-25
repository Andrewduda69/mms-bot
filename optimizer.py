import requests
import pandas as pd
import numpy as np
from itertools import product
from datetime import datetime, timezone

# ─── KONFIGURACJA ─────────────────────────────────────────
BOT_TOKEN = "8409956991:AAHtQm-3YY09DLjIGoTSqudtMd_wgq_d2FM"
CHAT_ID   = "-5299312717"

KAPITAL     = 25000
RYZYKO_PCT  = 1.0    # 1% na pozycję
MAX_DD_PCT  = 5.0    # max akceptowalny DD %
DNI_LOOKBACK = 15    # ile dni wstecz testujemy

# Grid parametrów
ATR_MULTS   = [1.5, 2.0, 2.5, 3.0]
TMA_LENS    = [100, 150, 200, 240, 300]
ATR_PERIODS = [1, 2, 3, 5, 14]

# ─── FUNKCJE ──────────────────────────────────────────────
def send_telegram(msg):
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": msg}
    )

def get_klines(interval="15m", limit=1000):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    df = pd.DataFrame(r.json(), columns=[
        "time","open","high","low","close","volume",
        "close_time","quote_volume","trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ])
    df = df[["time","open","high","low","close","volume"]].astype(float)
    df["ts"] = pd.to_datetime(df["time"], unit="ms")
    return df

def tma(series, length):
    return series.rolling(length).mean().rolling(length).mean()

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

def get_h4_campaign(df_h4):
    h4_chg = (df_h4["close"].iloc[-2] - df_h4["open"].iloc[-2]) / df_h4["open"].iloc[-2] * 100
    if h4_chg < -0.5:
        return "BEARISH"
    elif h4_chg > 0.5:
        return "BULLISH"
    return "NEUTRAL"

def qty_base(price):
    risk = KAPITAL * RYZYKO_PCT / 100
    return round(risk / (price * 0.02), 4)

def qty_dok(price):
    risk = KAPITAL * RYZYKO_PCT / 100
    return round(risk / (price * 0.01), 4)

def backtest(df, df_h4, atr_mult, tma_len, atr_period):
    # Indicators
    tma_mid = tma(df["close"], tma_len)
    atr_val = atr_calc(df, atr_period)
    upper   = tma_mid + atr_mult * atr_val
    lower   = tma_mid - atr_mult * atr_val
    stoch   = stochastic(df)

    trades = []
    equity = [KAPITAL]
    max_eq = KAPITAL
    max_dd = 0

    state = {
        "direction":     None,
        "entry":         None,
        "sl":            None,
        "base_bar":      None,
        "dokladka_done": False,
        "pending":       None,
        "pending_bar":   None,
        "size_mult":     1.0,
    }

    start = max(tma_len * 2, atr_period + 1, 300)

    for i in range(start, len(df) - 1):
        row        = df.iloc[i]
        close_p    = row["close"]
        bull       = row["close"] > row["open"]
        bear       = row["close"] < row["open"]
        ts         = row["ts"]
        is_weekend = ts.weekday() in [5, 6]
        is_monday  = ts.weekday() == 0

        h4_camp       = get_h4_campaign(df_h4)
        blocks_long   = h4_camp == "BEARISH"
        blocks_short  = h4_camp == "BULLISH"

        touched_lower = row["low"]  <= lower.iloc[i]
        touched_upper = row["high"] >= upper.iloc[i]
        is_os         = stoch.iloc[i] <= 20
        is_ob         = stoch.iloc[i] >= 80

        can_trade = not is_weekend and not is_monday
        sl_long   = round(close_p * 0.98, 1)
        sl_short  = round(close_p * 1.02, 1)
        size_b    = qty_base(close_p) * state["size_mult"]
        size_d    = qty_dok(close_p)

        # SL check
        if state["direction"] == "LONG" and row["low"] <= state["sl"]:
            pnl = (state["sl"] - state["entry"]) * size_b
            trades.append(pnl)
            eq = equity[-1] + pnl
            equity.append(eq)
            max_eq = max(max_eq, eq)
            dd = (max_eq - eq) / max_eq * 100
            max_dd = max(max_dd, dd)
            state = {**state, "direction": None, "entry": None, "sl": None,
                     "base_bar": None, "dokladka_done": False,
                     "pending": None, "pending_bar": None, "size_mult": 0.1}

        elif state["direction"] == "SHORT" and row["high"] >= state["sl"]:
            pnl = (state["entry"] - state["sl"]) * size_b
            trades.append(pnl)
            eq = equity[-1] + pnl
            equity.append(eq)
            max_eq = max(max_eq, eq)
            dd = (max_eq - eq) / max_eq * 100
            max_dd = max(max_dd, dd)
            state = {**state, "direction": None, "entry": None, "sl": None,
                     "base_bar": None, "dokladka_done": False,
                     "pending": None, "pending_bar": None, "size_mult": 0.1}

        # CUT AND REVERSE
        if state["direction"] == "LONG":
            if touched_upper and bear and is_ob and not blocks_short:
                pnl = (close_p - state["entry"]) * size_b
                trades.append(pnl)
                eq = equity[-1] + pnl
                equity.append(eq)
                max_eq = max(max_eq, eq)
                if pnl > 0:
                    state["size_mult"] = 1.0
                state["direction"]     = "SHORT"
                state["entry"]         = close_p
                state["sl"]            = sl_short
                state["base_bar"]      = i
                state["dokladka_done"] = False

        elif state["direction"] == "SHORT":
            if touched_lower and bull and is_os and not blocks_long:
                pnl = (state["entry"] - close_p) * size_b
                trades.append(pnl)
                eq = equity[-1] + pnl
                equity.append(eq)
                max_eq = max(max_eq, eq)
                if pnl > 0:
                    state["size_mult"] = 1.0
                state["direction"]     = "LONG"
                state["entry"]         = close_p
                state["sl"]            = sl_long
                state["base_bar"]      = i
                state["dokladka_done"] = False

        # PENDING
        if state["direction"] is None and state["pending"] is None and can_trade:
            if touched_lower and is_os and bull and not blocks_long:
                state["pending"]     = "LONG"
                state["pending_bar"] = i
            elif touched_upper and is_ob and bear and not blocks_short:
                state["pending"]     = "SHORT"
                state["pending_bar"] = i

        # POTWIERDZENIE
        if state["pending"] == "LONG" and i == state["pending_bar"] + 1:
            if bull:
                state["direction"]     = "LONG"
                state["entry"]         = close_p
                state["sl"]            = sl_long
                state["base_bar"]      = i
                state["dokladka_done"] = False
            state["pending"] = None
            state["pending_bar"] = None

        elif state["pending"] == "SHORT" and i == state["pending_bar"] + 1:
            if bear:
                state["direction"]     = "SHORT"
                state["entry"]         = close_p
                state["sl"]            = sl_short
                state["base_bar"]      = i
                state["dokladka_done"] = False
            state["pending"] = None
            state["pending_bar"] = None

        # DOKŁADKA
        if (state["direction"] == "LONG" and not state["dokladka_done"] and
            state["base_bar"] is not None and i == state["base_bar"] + 1 and bull):
            pnl_dok = 0  # dokładka liczona przy zamknięciu
            state["dokladka_done"] = True

        if (state["direction"] == "SHORT" and not state["dokladka_done"] and
            state["base_bar"] is not None and i == state["base_bar"] + 1 and bear):
            state["dokladka_done"] = True

    if len(trades) == 0:
        return 0, 0, 0

    total_pnl = sum(trades)
    pct       = total_pnl / KAPITAL * 100
    return round(pct, 2), round(max_dd, 2), len(trades)


def run_optimization():
    send_telegram("🔍 Parametryzacja startuje — testowanie kombinacji...")

    df    = get_klines("15m", 1440)  # ~15 dni
    df_h4 = get_klines("4h", 100)

    best_pct    = -999
    best_params = None
    best_dd     = 0
    best_trades = 0
    results     = []

    total = len(ATR_MULTS) * len(TMA_LENS) * len(ATR_PERIODS)
    tested = 0

    for atr_mult, tma_len, atr_period in product(ATR_MULTS, TMA_LENS, ATR_PERIODS):
        pct, dd, n_trades = backtest(df, df_h4, atr_mult, tma_len, atr_period)
        tested += 1

        if dd <= MAX_DD_PCT and pct > best_pct and n_trades >= 5:
            best_pct    = pct
            best_params = (atr_mult, tma_len, atr_period)
            best_dd     = dd
            best_trades = n_trades

        results.append((atr_mult, tma_len, atr_period, pct, dd, n_trades))

    if best_params is None:
        send_telegram("⚠️ Nie znaleziono parametrów spełniających kryteria DD. Zostawiam poprzednie.")
        return None

    send_telegram(
        f"✅ Parametryzacja zakończona!\n"
        f"Testowano: {tested} kombinacji\n"
        f"─────────────────\n"
        f"Najlepsze parametry:\n"
        f"ATR Mult: {best_params[0]}\n"
        f"TMA Len:  {best_params[1]}\n"
        f"ATR Period: {best_params[2]}\n"
        f"─────────────────\n"
        f"Wynik: +{best_pct}%\n"
        f"Max DD: {best_dd}%\n"
        f"Tradów: {best_trades}\n"
        f"─────────────────\n"
        f"Zaktualizuj TV: {best_params[0]} / {best_params[1]} / {best_params[2]}"
    )

    return best_params


if __name__ == "__main__":
    run_optimization()
