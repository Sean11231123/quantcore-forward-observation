# v9_v2_strategy.py
"""
V9 v2 Short-Term Trend System
Signal-based edge (NOT execution-based)
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
from config import ATR_PERIOD, ADX_PERIOD, RSI_PERIOD
from config_v9_v2 import (
    V9_V2_EMA_FAST, V9_V2_EMA_MID, V9_V2_EMA_SLOW,
    V9_V2_ADX_MIN, V9_V2_ATR_PERCENTILE, V9_V2_RSI_MIN, V9_V2_RSI_MAX,
    V9_V2_BODY_ATR_MIN, V9_V2_DISTANCE_FROM_EMA50,
    V9_V2_SL_ATR, V9_V2_TP_ATR, V9_V2_BE_TRIGGER_ATR,
)

class Signal(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"

@dataclass
class TradeSignal:
    signal: Signal
    entry_price: float
    stop_loss: float
    take_profit: float
    atr: float
    reason: str

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all required indicators"""
    df = df.copy()
    
    # EMA
    df["ema20"] = df["close"].ewm(span=V9_V2_EMA_FAST, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=V9_V2_EMA_MID, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=V9_V2_EMA_SLOW, adjust=False).mean()
    
    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    df["rsi"] = np.where(loss == 0, 100.0, 100 - 100 / (1 + gain / loss.where(loss != 0, np.nan)))
    
    # ATR
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=ATR_PERIOD).mean()
    df["atr_percentile"] = df["atr"].rolling(100).rank(pct=True) * 100
    
    # ADX
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_adx = tr.ewm(alpha=1/ADX_PERIOD, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/ADX_PERIOD, adjust=False).mean() / atr_adx
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/ADX_PERIOD, adjust=False).mean() / atr_adx
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1/ADX_PERIOD, adjust=False).mean()
    
    return df

def check_trend_filter(df: pd.DataFrame, idx: int) -> tuple:
    """Check market regime filter"""
    row = df.iloc[idx]
    
    # ADX filter
    adx_pass = row["adx"] >= V9_V2_ADX_MIN
    
    # ATR percentile filter
    atr_pass = row["atr_percentile"] >= V9_V2_ATR_PERCENTILE
    
    # EMA trend direction
    if pd.isna(row["ema50"]) or pd.isna(row["ema200"]):
        return False, None, "ema_nan"
    
    trend_long = row["ema50"] > row["ema200"]
    trend_short = row["ema50"] < row["ema200"]
    
    if adx_pass and atr_pass and trend_long:
        return True, "LONG", "trend_pass"
    elif adx_pass and atr_pass and trend_short:
        return True, "SHORT", "trend_pass"
    else:
        return False, None, f"adx={row['adx']:.1f}, atr_pct={row['atr_percentile']:.1f}"

def check_entry_long(df: pd.DataFrame, idx: int) -> tuple:
    """Check LONG entry conditions"""
    row = df.iloc[idx]
    prev = df.iloc[idx - 1] if idx > 0 else row
    
    reasons = []
    
    # 1. Pullback to EMA20 or EMA50
    ema20_dist = abs(row["close"] - row["ema20"]) / row["atr"] if row["atr"] > 0 else 999
    ema50_dist = abs(row["close"] - row["ema50"]) / row["atr"] if row["atr"] > 0 else 999
    
    if ema20_dist > V9_V2_DISTANCE_FROM_EMA50 and ema50_dist > V9_V2_DISTANCE_FROM_EMA50:
        return False, "no_pullback"
    
    # 2. Bullish confirmation
    bullish_engulfing = (row["close"] > row["open"]) and (prev["close"] < prev["open"]) and \
                        (row["close"] > prev["open"]) and (row["open"] < prev["close"])
    strong_close = row["close"] > prev["high"]
    
    if not (bullish_engulfing or strong_close):
        return False, "no_confirmation"
    
    # 3. RSI between 40-60
    if not (V9_V2_RSI_MIN <= row["rsi"] <= V9_V2_RSI_MAX):
        return False, f"rsi={row['rsi']:.1f}"
    
    # 4. Body size filter
    body_size = abs(row["close"] - row["open"])
    if body_size < V9_V2_BODY_ATR_MIN * row["atr"]:
        return False, "body_too_small"
    
    return True, "entry_pass"

def generate_signal(df: pd.DataFrame, idx: int) -> TradeSignal:
    """Generate trading signal"""
    if idx < 200 or idx >= len(df):
        return TradeSignal(Signal.NONE, 0, 0, 0, 0, "insufficient_data")
    
    row = df.iloc[idx]
    
    # Check trend filter
    trend_pass, direction, reason = check_trend_filter(df, idx)
    if not trend_pass:
        return TradeSignal(Signal.NONE, row["close"], 0, 0, row["atr"], f"trend_filter: {reason}")
    
    # Check entry (LONG only for v2)
    if direction == "LONG":
        entry_pass, reason = check_entry_long(df, idx)
        if not entry_pass:
            return TradeSignal(Signal.NONE, row["close"], 0, 0, row["atr"], f"entry_filter: {reason}")
        
        # Calculate SL/TP
        entry = row["close"]
        atr = row["atr"]
        sl = entry - (V9_V2_SL_ATR * atr)
        tp = entry + (V9_V2_TP_ATR * atr)
        
        return TradeSignal(
            signal=Signal.LONG,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            atr=atr,
            reason=f"LONG: RSI={row['rsi']:.1f}, ADX={row['adx']:.1f}"
        )
    
    return TradeSignal(Signal.NONE, row["close"], 0, 0, row["atr"], "no_signal")
