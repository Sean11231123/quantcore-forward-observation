from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pandas as pd

from engine import ENGINE_CONFIG, TradingEngine
import scripts.run_v12_scan_once as scan_once


SYMBOL = "BTC/USDT:USDT"


def _synthetic_ohlcv() -> pd.DataFrame:
    """Deterministic closed-bar OHLCV fixture; no network access."""
    now = pd.Timestamp.now(tz="UTC")
    start = now - pd.Timedelta(minutes=15 * 305)
    timestamps = pd.date_range(
        start,
        periods=300,
        freq="15min",
        tz="UTC",
    )

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [78000.0] * 300,
            "high": [78100.0] * 300,
            "low": [77900.0] * 300,
            "close": [78050.0] * 300,
            "volume": [1.0] * 300,
        }
    )


def _synthetic_trending_bull_regime():
    """
    Interface-compatible synthetic regime.

    Production _regime_cache stores:
        (regime, time.time())

    _signal_generation_once() accesses:
        regime.regime.value
    """
    return SimpleNamespace(
        regime=SimpleNamespace(value="trending_bull"),
    )


def test_strategy_exception_is_recorded_by_engine(monkeypatch):
    """
    Verify the real _signal_generation_once() exception boundary:

        strategy.generate_signal()
            -> engine._last_strategy_errors

    No Binance/network access is permitted.
    """
    engine = TradingEngine(ENGINE_CONFIG)

    try:
        engine._regime_cache[SYMBOL] = (
            _synthetic_trending_bull_regime(),
            0.0,
        )

        strategy_set = engine.strategy_sets[SYMBOL]
        strategy = strategy_set["strategies"]["v12_trend"]

        monkeypatch.setattr(
            strategy_set["router"],
            "route",
            lambda regime: ["v12_trend"],
        )

        def raise_test_exception(**kwargs):
            raise ValueError("test-induced failure")

        monkeypatch.setattr(
            strategy,
            "generate_signal",
            raise_test_exception,
        )

        async def fake_fetch_ohlcv_df(
            symbol,
            timeframe=None,
            limit=None,
        ):
            return _synthetic_ohlcv()

        monkeypatch.setattr(
            engine,
            "_fetch_ohlcv_df",
            fake_fetch_ohlcv_df,
        )

        asyncio.run(engine._signal_generation_once())

        assert len(engine._last_strategy_errors) == 1
        assert (
            engine._last_strategy_errors[0]
            == f"{SYMBOL}/v12_trend: test-induced failure"
        )
    finally:
        asyncio.run(engine._cleanup())


def test_scan_wrapper_reports_strategy_execution_error(monkeypatch):
    """
    Verify the complete Finding F observability path without network
    access or production heartbeat-file writes:

        synthetic regime
            -> real _signal_generation_once()
            -> real strategy exception handler
            -> _last_strategy_errors
            -> real scan wrapper logic
            -> captured heartbeat row
            -> strategy_execution_error
    """

    captured_heartbeat = []

    def capture_heartbeat(row):
        captured_heartbeat.append(dict(row))

    monkeypatch.setattr(
        scan_once,
        "append_heartbeat",
        capture_heartbeat,
    )

    original_engine_class = scan_once.TradingEngine

    class OfflineTestEngine(original_engine_class):
        async def _regime_detection_once(self):
            self._regime_cache[SYMBOL] = (
                _synthetic_trending_bull_regime(),
                0.0,
            )

        async def _cleanup(self):
            return None

    monkeypatch.setattr(
        scan_once,
        "TradingEngine",
        OfflineTestEngine,
    )

    original_signal_generation_once = (
        OfflineTestEngine._signal_generation_once
    )

    async def controlled_signal_generation_once(self):
        strategy_set = self.strategy_sets[SYMBOL]
        strategy = strategy_set["strategies"]["v12_trend"]

        monkeypatch.setattr(
            strategy_set["router"],
            "route",
            lambda regime: ["v12_trend"],
        )

        def raise_test_exception(**kwargs):
            raise ValueError("test-induced failure")

        monkeypatch.setattr(
            strategy,
            "generate_signal",
            raise_test_exception,
        )

        async def fake_fetch_ohlcv_df(
            symbol,
            timeframe=None,
            limit=None,
        ):
            return _synthetic_ohlcv()

        monkeypatch.setattr(
            self,
            "_fetch_ohlcv_df",
            fake_fetch_ohlcv_df,
        )

        await original_signal_generation_once(self)

    monkeypatch.setattr(
        OfflineTestEngine,
        "_signal_generation_once",
        controlled_signal_generation_once,
    )

    exit_code = asyncio.run(scan_once.main())

    assert exit_code == 0
    assert len(captured_heartbeat) == 1

    captured_summary = captured_heartbeat[0]

    assert (
        captured_summary["heartbeat_state"]
        == "strategy_execution_error"
    )

    assert captured_summary["errors_json"]
    assert "test-induced failure" in captured_summary["errors_json"]
    assert f"{SYMBOL}/v12_trend" in captured_summary["errors_json"]

