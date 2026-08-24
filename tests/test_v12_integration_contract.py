"""
Regression tests — V12 integration contract restoration.

Validation levels covered:
  Level 1    : interface / data-plumbing contract (full adapter kwargs)
  Lookahead  : mandatory closed-bar / no-future-leak temporal semantics
  Level 2    : historical signal-schema sanity (field presence + values)
  Governance : frozen-config guards (execute_orders, universe, 0.22)

Level 3 (deterministic replay of 2026-05-04) is NOT COVERED here:
the original OHLCV required for replay is not available in this repository.

Run from repository root:
    python -m pytest tests/test_v12_integration_contract.py -v
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import ENGINE_CONFIG, TradingEngine
from v12_strategy import (
    align_1h_adx_to_15m,
    compute_v12_15m,
    shift_candle_open_to_close,
)


SYMBOL = "BTC/USDT:USDT"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_ohlcv(
    start: datetime,
    periods: int,
    freq_min: int,
    base_price: float = 100.0,
    seed: int = 7,
) -> pd.DataFrame:
    """Deterministic synthetic OHLCV with candle-OPEN timestamps (tz-aware UTC)."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=periods, freq=f"{freq_min}min", tz="UTC")
    steps = rng.normal(0.0, base_price * 0.002, periods)
    close = base_price + np.cumsum(steps)
    open_ = np.concatenate([[base_price], close[:-1]])
    high = np.maximum(open_, close) + rng.uniform(0.0, base_price * 0.001, periods)
    low = np.minimum(open_, close) - rng.uniform(0.0, base_price * 0.001, periods)
    vol = rng.uniform(100.0, 1000.0, periods)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )


def make_engine() -> TradingEngine:
    cfg = deepcopy(ENGINE_CONFIG)
    cfg["exchanges"]["binance"]["api_key"] = "test-key"
    cfg["exchanges"]["binance"]["api_secret"] = "test-secret"
    return TradingEngine(cfg)


class StubConnector:
    """Offline stand-in for ExchangeConnector returning raw ccxt-style rows."""

    def __init__(self, data: dict[tuple[str, str], pd.DataFrame]):
        self.data = data
        self.calls: list[tuple[str, str, int]] = []

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        self.calls.append((symbol, timeframe, limit))
        df = self.data.get((symbol, timeframe))
        if df is None:
            return []
        return [
            [int(t.timestamp() * 1000), o, h, l, c, v]
            for t, o, h, l, c, v in zip(
                df["timestamp"], df["open"], df["high"], df["low"], df["close"], df["volume"]
            )
        ]

    async def close(self):
        pass


def fake_regime(trend_strength: float = 36.8):
    return SimpleNamespace(
        regime=SimpleNamespace(value="trend_up"),
        confidence=0.9,
        recommended_strategies=["v12_trend"],
        trend_strength=trend_strength,
        volatility=0.4,
    )


class CaptureStrategy:
    """Records the exact kwargs the engine supplies to the V12 adapter."""

    name = "v12_trend"

    def __init__(self):
        self.kwargs: dict | None = None

    def generate_signal(self, **kwargs):
        self.kwargs = kwargs
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Governance guards (frozen constraints)
# ─────────────────────────────────────────────────────────────────────────────

def test_frozen_execution_config_unchanged():
    """Governance: execute_orders=False and universe ['BTC/USDT:USDT'] frozen."""
    assert ENGINE_CONFIG["execute_orders"] is False
    assert ENGINE_CONFIG["symbols"] == ["BTC/USDT:USDT"]


def test_re_threshold_override_default_untouched():
    """Governance: adapter default re_threshold_override must remain 0.22."""
    v12_adapter = pytest.importorskip("core.strategies.v12_adapter")
    import inspect

    sig = inspect.signature(v12_adapter.V12Strategy.__init__)
    assert "re_threshold_override" in sig.parameters
    assert sig.parameters["re_threshold_override"].default == 0.22


# ─────────────────────────────────────────────────────────────────────────────
# Level 1 — interface / data-plumbing contract
# ─────────────────────────────────────────────────────────────────────────────

def test_signal_path_supplies_full_v12_contract():
    """
    Level 1: the forward signal path must fetch candidate 15m + candidate 1H
    + BTC 1H regime data and pass all three into the V12 adapter.
    """
    engine = make_engine()
    now = datetime.now(timezone.utc)

    # End each series >= 2 bars before real 'now' so every bar is closed.
    df15 = make_ohlcv(now - timedelta(minutes=15 * 82), 80, 15, seed=1)
    df1h = make_ohlcv(now - timedelta(hours=62), 60, 60, seed=11)

    stub = StubConnector({(SYMBOL, "15m"): df15, (SYMBOL, "1h"): df1h})
    engine.connectors = {"binance": stub}

    cap = CaptureStrategy()
    engine.strategy_sets[SYMBOL]["strategies"]["v12_trend"] = cap
    engine.strategy_sets[SYMBOL]["router"].route = lambda regime: ["v12_trend"]
    engine._regime_cache[SYMBOL] = (fake_regime(), time.time())

    asyncio.run(engine._signal_generation_once())

    # Both timeframes were actually requested from the connector.
    requested = {(s, tf) for s, tf, _ in stub.calls}
    assert (SYMBOL, "15m") in requested
    assert (SYMBOL, "1h") in requested

    # Adapter received the complete contract.
    assert cap.kwargs is not None, "adapter was never called"
    ohlcv_15m = cap.kwargs["ohlcv_15m"]
    ohlcv_1h = cap.kwargs["ohlcv_1h"]
    btc_regime = cap.kwargs["btc_regime"]

    assert isinstance(ohlcv_15m, pd.DataFrame) and not ohlcv_15m.empty
    assert isinstance(ohlcv_1h, pd.DataFrame) and not ohlcv_1h.empty
    assert isinstance(btc_regime, dict)
    assert "btc_adx_1h" in btc_regime and "btc_re" in btc_regime
    assert math.isfinite(float(btc_regime["btc_adx_1h"]))
    assert math.isfinite(float(btc_regime["btc_re"]))

    # Closed-bar property on supplied frames (evaluation at real now).
    t_now = pd.Timestamp(datetime.now(timezone.utc))
    assert (ohlcv_15m["timestamp"].iloc[-1] + pd.Timedelta(minutes=15)) <= t_now
    assert (ohlcv_1h["timestamp"].iloc[-1] + pd.Timedelta(hours=1)) <= t_now


# ─────────────────────────────────────────────────────────────────────────────
# Mandatory lookahead / closed-bar semantics
# ─────────────────────────────────────────────────────────────────────────────

def test_filter_closed_bars_drops_forming_and_future_bars():
    """Evaluation at t cannot consume a forming bar (close > t) or a future bar."""
    engine = make_engine()
    now = datetime.now(timezone.utc)
    opens = [
        now - timedelta(hours=4),    # closes now-3h  -> keep
        now - timedelta(hours=3),    # closes now-2h  -> keep
        now - timedelta(minutes=90), # closes now-30m -> keep
        now - timedelta(minutes=30), # closes now+30m -> DROP (forming)
        now + timedelta(hours=2),    # closes now+3h  -> DROP (future)
    ]
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(opens, utc=True),
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        }
    )
    out = engine._filter_closed_bars(df, "1h", now=now)
    assert len(out) == 3
    assert out["timestamp"].iloc[-1] == pd.Timestamp(now - timedelta(minutes=90))


def test_filter_closed_bars_includes_bar_closing_exactly_at_t():
    """Boundary convention: close_time == t is USABLE (close known at instant t)."""
    engine = make_engine()
    now = datetime.now(timezone.utc)
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([now - timedelta(hours=1)], utc=True),
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        }
    )
    out = engine._filter_closed_bars(df, "1h", now=now)
    assert len(out) == 1


def test_shift_candle_open_to_close_semantics():
    """1H candle-open timestamps must shift forward by exactly one hour."""
    df = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-05-04 09:00", "2026-05-04 10:00"], utc=True)}
    )
    out = shift_candle_open_to_close(df, "1h")
    assert out["timestamp"].tolist() == [
        pd.Timestamp("2026-05-04 10:00", tz="UTC"),
        pd.Timestamp("2026-05-04 11:00", tz="UTC"),
    ]


def test_align_1h_adx_backward_merge_no_future_leak():
    """
    Core no-lookahead proof: for EVERY 15m row at time t, the merged adx_1h
    must equal the ADX of the last 1H bar whose CLOSE time <= t — verified
    against an independently truncated reference (not implementation internals).
    """
    start = pd.Timestamp("2026-05-01 00:00", tz="UTC")
    n1h = 60
    df1h = make_ohlcv(start.to_pydatetime(), n1h, 60, seed=3)

    # Force an ADX contrast between halves so picking a LATER bar than allowed
    # would produce a detectably different value.
    strong = np.linspace(0.0, 30.0, 30)
    anchor = float(df1h["close"].iloc[29])
    df1h.loc[df1h.index[30:], "close"] = anchor + strong
    df1h.loc[df1h.index[30:], "open"] = anchor + np.concatenate([[0.0], strong[:-1]])
    df1h.loc[df1h.index[30:], "high"] = (
        df1h[["open", "close"]].max(axis=1).iloc[30:] + 0.5
    )
    df1h.loc[df1h.index[30:], "low"] = (
        df1h[["open", "close"]].min(axis=1).iloc[30:] - 0.5
    )

    start15 = start + pd.Timedelta(hours=20)
    df15 = make_ohlcv(start15.to_pydatetime(), 80, 15, seed=4)

    merged = align_1h_adx_to_15m(df15, df1h)
    assert "adx_1h" in merged.columns

    # Independent reference: 1H ADX keyed by candle-CLOSE time.
    ref = shift_candle_open_to_close(compute_v12_15m(df1h), "1h")[
        ["timestamp", "adx"]
    ].sort_values("timestamp").reset_index(drop=True)

    for _, row in merged.iterrows():
        t = row["timestamp"]
        eligible = ref[ref["timestamp"] <= t]
        assert not eligible.empty, f"no closed 1H bar available at {t}"
        expected = eligible["adx"].iloc[-1]
        got = row["adx_1h"]
        if pd.isna(expected):
            assert pd.isna(got)
        else:
            assert got == pytest.approx(float(expected), abs=1e-9)

    # Explicit boundary: a 15m stamp exactly at a 1H close time must consume
    # THAT bar (inclusive), never the following one.
    boundary = start + pd.Timedelta(hours=31)
    assert (ref["timestamp"] == boundary).any(), "boundary 1H close missing"
    brows = merged[merged["timestamp"] == boundary]
    assert len(brows) == 1
    expected = ref.loc[ref["timestamp"] == boundary, "adx"].iloc[-1]
    assert brows["adx_1h"].iloc[0] == pytest.approx(float(expected), abs=1e-9)


def test_build_btc_regime_matches_manual_range_efficiency():
    """BTC RE must equal |C_t - C_{t-20}| / (HH20 - LL20) on closed BTC 1H bars."""
    engine = make_engine()
    now = datetime.now(timezone.utc)
    df1h = make_ohlcv(now - timedelta(hours=82), 80, 60, seed=5)
    closed = engine._filter_closed_bars(df1h, "1h", now=now)
    assert len(closed) >= 21

    regime = engine._build_btc_regime(closed)

    c = closed["close"].reset_index(drop=True)
    h = closed["high"].reset_index(drop=True)
    l = closed["low"].reset_index(drop=True)
    denom = float(h.iloc[-20:].max() - l.iloc[-20:].min())
    assert denom > 0
    expected_re = abs(float(c.iloc[-1]) - float(c.iloc[-21])) / denom

    assert regime["btc_re"] == pytest.approx(expected_re, rel=1e-9)
    assert 0.0 <= float(regime["btc_adx_1h"]) < 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Enrichment schema fidelity (adx_confirm_tf = TRUE 1H confirmation ADX)
# ─────────────────────────────────────────────────────────────────────────────

def test_enrichment_adx_confirm_tf_uses_1h_confirmation():
    """
    Historical records show adx_confirm_tf distinct from the 15m entry ADX
    (e.g. 34.5 vs 38.2). Enrichment must therefore derive adx_confirm_tf from
    the 1H confirmation series via the existing backward merge, not fall back
    to the 15m ADX.
    """
    engine = make_engine()
    now = datetime.now(timezone.utc)
    df15 = engine._filter_closed_bars(
        make_ohlcv(now - timedelta(minutes=15 * 82), 80, 15, seed=21), "15m", now=now
    )
    df1h = engine._filter_closed_bars(
        make_ohlcv(now - timedelta(hours=62), 60, 60, seed=22), "1h", now=now
    )

    meta = engine._extract_signal_metadata(df15, df1h)

    # Independent reference: last 1H bar whose CLOSE time <= last 15m stamp.
    ref = shift_candle_open_to_close(compute_v12_15m(df1h), "1h")[
        ["timestamp", "adx"]
    ].sort_values("timestamp").reset_index(drop=True)
    t_last = df15["timestamp"].iloc[-1]
    eligible = ref[ref["timestamp"] <= t_last]
    assert not eligible.empty
    expected = eligible["adx"].iloc[-1]

    if pd.isna(expected):
        assert pd.isna(meta["adx_confirm_tf"]) or meta["adx_confirm_tf"] == ""
    else:
        assert meta["adx_confirm_tf"] == pytest.approx(float(expected), rel=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# Level 2 — historical signal-schema sanity
# ─────────────────────────────────────────────────────────────────────────────

def test_v12_signal_schema_fields_present():
    """
    Level 2: emitted V12 signal record carries the historical schema fields
    (entry, ADX entry/confirm, BTC RE, BTC ADX confirm) with sane values.
    """
    engine = make_engine()
    now = datetime.now(timezone.utc)
    df15 = make_ohlcv(now - timedelta(hours=21), 80, 15, seed=9)
    df1h = make_ohlcv(now - timedelta(hours=62), 60, 60, seed=10)

    signal = SimpleNamespace(
        symbol=SYMBOL,
        side="buy",
        price=78400.0,
        stop_loss=77000.0,
        take_profit=81000.0,
        quantity=0.001,
        confidence=0.8,
        timestamp=time.time(),
        metadata={"btc_re": 0.31},
        strategy_name="v12_trend",
    )
    regime = fake_regime(trend_strength=36.8)

    data = engine._build_v12_signal_data(signal, regime, df15, df1h)

    for key in (
        "entry_price",
        "stop_loss",
        "take_profit",
        "adx_entry_tf",
        "adx_confirm_tf",
        "btc_re",
        "btc_adx_confirm_tf",
        "atr",
        "rsi_14",
        "macd",
        "strategy_name",
        "timeframe",
    ):
        assert key in data, f"missing schema field: {key}"

    assert data["entry_price"] == 78400.0
    assert data["strategy_name"] == "V12_C3"
    assert data["timeframe"] == "15m"
    assert data["btc_adx_confirm_tf"] == pytest.approx(36.8)
    assert data["btc_re"] == pytest.approx(0.31)
    assert float(data["adx_entry_tf"]) >= 0.0
    assert float(data["adx_confirm_tf"]) >= 0.0
    assert float(data["atr"]) > 0.0
