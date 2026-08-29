"""
Layer 6: Trading Engine Orchestrator

Phase 3 testnet smoke engine:
- reads Binance Futures Testnet OHLCV
- detects market regime
- routes only to V12_C3_15m_clean forward stream
- logs generated signals
- does not place live orders unless execute_orders=True is set in ENGINE_CONFIG

V12 integration contract (restored):
- candidate 15m OHLCV  -> V12 adapter entry timeframe
- candidate 1H OHLCV   -> V12 adapter 1H ADX confirmation
- BTC 1H OHLCV         -> BTC ADX (btc_adx_1h; canonical source, unchanged)
- BTC 15m OHLCV        -> BTC RE (btc_re; F-5(a) Backtest canonical
                          definition: 20-bar range efficiency on BTC 15m,
                          asof-backward aligned to each candidate 15m candle)
All bars supplied to the strategy are fully CLOSED at evaluation time
(mandatory no-lookahead policy, see _filter_closed_bars).
"""

from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd

from config import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    OKX_API_KEY,
    OKX_API_SECRET,
    OKX_PASSPHRASE,
)
from core.exchange import ExchangeConnector
from core.market_regime import MarketRegimeDetector
from core.router import StrategyRouter
from core.strategies.base import Signal, StrategyConfig


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("TradingEngine")


ENGINE_CONFIG = {
    "symbols": ["BTC/USDT:USDT"],
    "timeframe": "1h",
    "ohlcv_limit": 200,
    "capital_usdt": 100,
    "regime_check_interval": 300,
    "signal_check_interval": 60,
    "mm_quote_interval": 10,
    "execute_orders": False,
    "exchanges": {
        "binance": {
            "api_key": BINANCE_API_KEY,
            "api_secret": BINANCE_API_SECRET,
            "testnet": True,
        },
        "okx": {
            "api_key": OKX_API_KEY,
            "api_secret": OKX_API_SECRET,
            "passphrase": OKX_PASSPHRASE,
            "testnet": True,
        },
    },
}

# ── V12 C3 data-contract constants (integration layer only) ─────────────────
# Frozen elsewhere (DO NOT CHANGE HERE):
#   universe ["BTC/USDT:USDT"], execute_orders=False,
#   re_threshold_override=0.22 (governance finding under archaeology).
V12_ENTRY_TIMEFRAME = "15m"   # candidate entry timeframe required by V12 adapter
V12_CONFIRM_TIMEFRAME = "1h"  # candidate + BTC confirmation timeframe
V12_OHLCV_LIMIT = 300         # warmup headroom for ADX/EMA/RE indicators
V12_MIN_ENTRY_BARS = 200      # minimum closed 15m bars required by V12Strategy.generate_signal

# Timeframe duration map used by the closed-bar filter. Timestamps returned by
# the exchange are candle OPEN times; close_time = open_time + duration.
_CLOSED_BAR_DELTAS = {
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "2h": pd.Timedelta(hours=2),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}


@dataclass
class PortfolioState:
    capital_usdt: float
    peak_capital: float
    daily_start_capital: float
    open_positions: dict[str, dict] = field(default_factory=dict)
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    trade_count_today: int = 0
    last_reset_date: str = field(default_factory=lambda: str(date.today()))
    is_halted: bool = False
    halt_reason: str = ""


class TradingEngine:
    def __init__(self, config: dict):
        self.config = config
        cap = float(config.get("capital_usdt", 100))
        self.running = False
        self.portfolio = PortfolioState(
            capital_usdt=cap,
            peak_capital=cap,
            daily_start_capital=cap,
        )
        self.regime_detector = MarketRegimeDetector()
        self.connectors = self._setup_connectors()
        self.strategy_sets = self._setup_strategies()
        self._regime_cache: dict[str, tuple[object, float]] = {}
        self._trade_log: list[dict] = []
        self._signal_log: list[dict] = []
        self._lock = asyncio.Lock()
        self._last_regime_check = 0.0
        self._last_signal_check = 0.0

    def _setup_connectors(self) -> dict[str, ExchangeConnector]:
        connectors = {}
        for name, cfg in self.config["exchanges"].items():
            if not cfg.get("api_key") or not cfg.get("api_secret"):
                logger.warning("Skipping %s connector: missing API credentials", name)
                continue
            connectors[name] = ExchangeConnector(
                exchange=name,
                api_key=cfg["api_key"],
                api_secret=cfg["api_secret"],
                passphrase=cfg.get("passphrase", ""),
                testnet=cfg.get("testnet", True),
            )
        return connectors

    def _setup_strategies(self) -> dict[str, dict]:
        out = {}
        cap = float(self.config.get("capital_usdt", 100))
        for symbol in self.config["symbols"]:
            cfg = StrategyConfig(
                symbol=symbol,
                exchange="binance",
                capital_usdt=cap / max(len(self.config["symbols"]), 1),
            )
            strategies = {}
            try:
                from core.strategies.v12_adapter import V12Strategy

                strategies["v12_trend"] = V12Strategy(
                    cfg,
                    mode="C3",
                    adx_entry_override=30.0,
                    re_threshold_override=0.22,
                )
            except Exception as exc:
                logger.warning("V12Strategy unavailable for live engine: %s", exc)
            out[symbol] = {
                "strategies": strategies,
                "router": StrategyRouter(strategies),
                "config": cfg,
            }
        return out

    async def run(self):
        if self.running:
            return

        logger.info("Trading Engine starting in testnet smoke mode")
        self.running = True
        try:
            while self.running:
                now = time.time()
                if now - self._last_regime_check >= self.config["regime_check_interval"]:
                    await self._regime_detection_once()
                    self._last_regime_check = now

                if now - self._last_signal_check >= self.config["signal_check_interval"]:
                    await self._signal_generation_once()
                    self._last_signal_check = now

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Trading Engine cancelled")
            raise
        finally:
            self.running = False
            await self._cleanup()

    async def start(self):
        self.running = True
        self.portfolio.is_halted = False
        self.portfolio.halt_reason = ""

    async def prepare_start(self):
        self.portfolio.is_halted = False
        self.portfolio.halt_reason = ""

    async def stop(self):
        self.running = False

    async def halt(self, reason: str = "Manual halt from API"):
        self.running = False
        self.portfolio.is_halted = True
        self.portfolio.halt_reason = reason

    async def _fetch_ohlcv_df(
        self,
        symbol: str,
        timeframe: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        tf = timeframe or self.config.get("timeframe", "1h")
        raw = await self.connectors["binance"].fetch_ohlcv(
            symbol,
            tf,
            limit or self.config.get("ohlcv_limit", 200),
        )
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    @staticmethod
    def _filter_closed_bars(
        df: pd.DataFrame, timeframe: str, now: datetime | None = None
    ) -> pd.DataFrame:
        """
        Closed-bar policy (mandatory no-lookahead rule).

        Timestamp convention: exchange OHLCV timestamps are candle OPEN times.
        A bar is usable at evaluation time t iff:

            open_time + timeframe_duration <= t

        i.e. the bar is fully CLOSED at t. This simultaneously excludes:
          - the currently forming candle (its close occurs after t)
          - any future candle (open_time > t implies close_time > t)

        Boundary: a bar whose close_time == t IS usable (its close is known at
        instant t). This matches the inclusive convention already used by
        v12_strategy.align_1h_adx_to_15m (merge_asof direction="backward" on
        candle-CLOSE timestamps).
        """
        if df.empty:
            return df
        delta = _CLOSED_BAR_DELTAS.get(timeframe)
        if delta is None:
            raise ValueError(f"Unsupported timeframe for closed-bar filter: {timeframe}")
        t = pd.Timestamp(now or datetime.now(timezone.utc))
        ts = df["timestamp"]
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize("UTC")
        mask = (ts + delta) <= t
        return df.loc[mask].reset_index(drop=True)

    @staticmethod
    def _build_btc_regime(
        btc_1h_closed: pd.DataFrame,
        btc_15m_closed: pd.DataFrame | None = None,
        candidate_15m: pd.DataFrame | None = None,
    ) -> dict:
        """
        Build the existing V12 C3 BTC regime inputs.

        Canonical semantics (governance decision F-5(a)):
          - btc_adx_1h = ADX(14) on CLOSED BTC 1H bars       (UNCHANGED)
          - btc_re     = 20-bar range efficiency on CLOSED BTC 15m bars
                         (Backtest canonical definition; see
                         backtest/v12_backtest.py::_load_btc_regime, where
                         range_efficiency is computed on the BTC 15m frame
                         and renamed to btc_re)

        Alignment (Backtest canonical asof-backward semantics, replicated
        from backtest/v12_backtest.py::_prepare): with a candidate 15m frame
        supplied, select the latest BTC 15m candle whose OPEN timestamp is
        <= the candidate candle OPEN timestamp. On the shared 15-minute grid
        this is the contemporaneous candle, which closes together with the
        candidate bar. A newer BTC 15m candle that is merely closed at
        wall-clock scan time is NOT used.
        """
        from v12_strategy import compute_v12_15m

        regime: dict = {}

        if not btc_1h_closed.empty:
            feats_1h = compute_v12_15m(btc_1h_closed)
            row_1h = feats_1h.iloc[-1]
            adx = row_1h.get("adx")
            regime["btc_adx_1h"] = float(adx) if pd.notna(adx) else 0.0

        if btc_15m_closed is None or btc_15m_closed.empty:
            # Fail-closed: mirrors Backtest behaviour when BTC regime data
            # is absent (the C3 gate sees btc_re=0 and rejects the entry).
            regime["btc_re"] = 0.0
            return regime

        feats_15m = compute_v12_15m(btc_15m_closed)
        regime_15m = feats_15m[["timestamp", "range_efficiency"]].rename(
            columns={"range_efficiency": "btc_re"}
        )

        if candidate_15m is not None and not candidate_15m.empty:
            # Backtest canonical asof-backward alignment (identical mechanics
            # to _prepare in backtest/v12_backtest.py): candidate OPEN stamp
            # vs BTC 15m OPEN stamp, direction="backward".
            merged = pd.merge_asof(
                candidate_15m.sort_values("timestamp"),
                regime_15m.sort_values("timestamp"),
                on="timestamp",
                direction="backward",
            )
            re_value = merged["btc_re"].iloc[-1]
        else:
            re_value = feats_15m["range_efficiency"].iloc[-1]

        regime["btc_re"] = float(re_value) if pd.notna(re_value) else 0.0
        return regime

    async def _regime_detection_once(self):
        for symbol in self.config["symbols"]:
            try:
                df = await self._fetch_ohlcv_df(symbol)
                if df.empty:
                    logger.warning("%s regime skipped: no OHLCV data", symbol)
                    continue

                regime = self.regime_detector.detect(df)
                self._regime_cache[symbol] = (regime, time.time())
                logger.info(
                    "REGIME %s: %s conf=%.2f ADX=%.2f vol=%.2f strategies=%s",
                    symbol,
                    regime.regime.value,
                    regime.confidence,
                    regime.trend_strength,
                    regime.volatility,
                    regime.recommended_strategies,
                )
            except Exception as exc:
                logger.exception("Regime detection error for %s: %s", symbol, exc)

    async def _signal_generation_once(self):
        if self.portfolio.is_halted:
            logger.warning("Signal generation skipped: halted (%s)", self.portfolio.halt_reason)
            return

        now = datetime.now(timezone.utc)

        # ── V12 C3 data contract: BTC regime inputs ─────────────────────
        # btc_adx_1h <- BTC 1H (canonical source, unchanged)
        # btc_re     <- BTC 15m (F-5(a): Backtest canonical definition,
        #               20-bar range efficiency on BTC 15m; asof-backward
        #               aligned to each candidate 15m candle OPEN stamp).
        # NOTE: the additional BTC 15m fetch is NOT universe expansion;
        # BTC/USDT:USDT is the already-configured candidate symbol.
        btc_1h_closed: pd.DataFrame = pd.DataFrame()
        btc_15m_closed: pd.DataFrame = pd.DataFrame()
        try:
            btc_raw_1h = await self._fetch_ohlcv_df(
                "BTC/USDT:USDT",
                timeframe=V12_CONFIRM_TIMEFRAME,
                limit=V12_OHLCV_LIMIT,
            )
            btc_1h_closed = self._filter_closed_bars(btc_raw_1h, V12_CONFIRM_TIMEFRAME, now=now)
        except Exception as exc:
            logger.warning("BTC 1H regime data unavailable: %s", exc)
        try:
            btc_raw_15m = await self._fetch_ohlcv_df(
                "BTC/USDT:USDT",
                timeframe=V12_ENTRY_TIMEFRAME,
                limit=V12_OHLCV_LIMIT,
            )
            btc_15m_closed = self._filter_closed_bars(btc_raw_15m, V12_ENTRY_TIMEFRAME, now=now)
        except Exception as exc:
            logger.warning("BTC 15m regime data unavailable: %s", exc)

        for symbol in self.config["symbols"]:
            try:
                if symbol not in self._regime_cache:
                    logger.info("SIGNAL %s skipped: no regime yet", symbol)
                    continue

                # ── V12 C3 data contract: candidate 15m + candidate 1H ─────
                df15_raw = await self._fetch_ohlcv_df(
                    symbol, timeframe=V12_ENTRY_TIMEFRAME, limit=V12_OHLCV_LIMIT
                )
                df1h_raw = await self._fetch_ohlcv_df(
                    symbol, timeframe=V12_CONFIRM_TIMEFRAME, limit=V12_OHLCV_LIMIT
                )
                df15 = self._filter_closed_bars(df15_raw, V12_ENTRY_TIMEFRAME, now=now)
                df1h = self._filter_closed_bars(df1h_raw, V12_CONFIRM_TIMEFRAME, now=now)
                if df15.empty or df1h.empty:
                    logger.warning(
                        "%s signal skipped: incomplete OHLCV (15m=%d bars, 1h=%d bars)",
                        symbol,
                        len(df15),
                        len(df1h),
                    )
                    continue
                if len(df15) < V12_MIN_ENTRY_BARS:
                    logger.warning(
                        "%s signal skipped: insufficient closed 15m bars "
                        "(%d available, %d required by V12 adapter)",
                        symbol,
                        len(df15),
                        V12_MIN_ENTRY_BARS,
                    )
                    continue
                logger.info(
                    "DATA %s: 15m=%d bars, 1h=%d bars (closed-bar filtered)",
                    symbol,
                    len(df15),
                    len(df1h),
                )

                # ── BTC regime (per-candidate asof alignment) ───────────
                try:
                    btc_regime = self._build_btc_regime(btc_1h_closed, btc_15m_closed, df15)
                except Exception as exc:
                    logger.warning("BTC regime build failed for %s: %s", symbol, exc)
                    btc_regime = {}
                logger.info(
                    "BTC REGIME INPUTS: adx_1h=%s re=%s "
                    "(btc_re: BTC 15m/20-bar, asof-backward vs candidate OPEN stamp)",
                    btc_regime.get("btc_adx_1h", ""),
                    btc_regime.get("btc_re", ""),
                )

                regime, _ = self._regime_cache[symbol]
                strategy_set = self.strategy_sets[symbol]
                active = strategy_set["router"].route(regime)
                logger.info("ROUTE %s: %s -> %s", symbol, regime.regime.value, active)

                for strategy_name in active:
                    try:
                        strategy = strategy_set["strategies"].get(strategy_name)
                        if strategy is None:
                            continue

                        signal = strategy.generate_signal(
                            ohlcv_15m=df15,
                            ohlcv_1h=df1h,
                            btc_regime=btc_regime,
                        )
                        if signal is None:
                            logger.info("SIGNAL %s/%s: none", symbol, strategy_name)
                            continue

                        if strategy_name == "v12_trend":
                            try:
                                from notifications.signal_pipeline import handle_v12_signal

                                pipeline_result = await handle_v12_signal(
                                    self._build_v12_signal_data(signal, regime, df15, df1h)
                                )
                                logger.info("V12 PIPELINE %s: %s", symbol, pipeline_result)
                            except Exception as exc:
                                logger.warning("V12 notification pipeline failed for %s: %s", symbol, exc)

                        self._record_signal(signal)
                        logger.info(
                            "SIGNAL %s/%s: side=%s price=%s qty=%.6f sl=%s tp=%s confidence=%.2f",
                            symbol,
                            strategy_name,
                            signal.side,
                            signal.price,
                            signal.quantity,
                            signal.stop_loss,
                            signal.take_profit,
                            signal.confidence,
                        )

                        if self.config.get("execute_orders", False):
                            await self._execute_signal(signal)
                    except Exception as exc:
                        logger.warning(
                            "Strategy %s/%s skipped after error: %s",
                            symbol,
                            strategy_name,
                            exc,
                        )
            except Exception as exc:
                logger.exception("Signal generation error for %s: %s", symbol, exc)

    def _record_signal(self, signal: Signal):
        self._signal_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": signal.symbol,
                "strategy": signal.strategy_name,
                "side": signal.side,
                "price": signal.price,
                "quantity": signal.quantity,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "confidence": signal.confidence,
                "status": "signal",
            }
        )
        self._signal_log = self._signal_log[-100:]

    def _build_v12_signal_data(
        self,
        signal: Signal,
        regime,
        ohlcv: pd.DataFrame | None = None,
        ohlcv_1h: pd.DataFrame | None = None,
    ) -> dict:
        metadata = signal.metadata or {}
        signal_timestamp = datetime.fromtimestamp(signal.timestamp, timezone.utc).isoformat()
        entry_price = signal.price if signal.price is not None else ""
        # ohlcv_1h is forwarded so adx_confirm_tf reflects the TRUE 1H
        # confirmation ADX (historical records show it distinct from the 15m
        # entry ADX), instead of falling back to the 15m value.
        enriched = self._extract_signal_metadata(ohlcv, ohlcv_1h)
        return {
            "signal_id": f"V12_C3_15m_clean_{signal.symbol}_{signal.side}_{signal_timestamp}_{entry_price}",
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "signal_timestamp": signal_timestamp,
            "strategy_name": "V12_C3",
            "strategy_version": "15m_clean",
            "timeframe": "15m",
            "research_tier": "primary",
            "symbol": signal.symbol,
            "side": signal.side,
            "entry_price": entry_price,
            "stop_loss": signal.stop_loss if signal.stop_loss is not None else "",
            "take_profit": signal.take_profit if signal.take_profit is not None else "",
            "atr": enriched.get("atr", metadata.get("atr", "")),
            "adx_entry_tf": enriched.get("adx_entry_tf", ""),
            "adx_confirm_tf": enriched.get("adx_confirm_tf", ""),
            "btc_re": metadata.get("btc_re", ""),
            "btc_adx_confirm_tf": regime.trend_strength if regime is not None else "",
            "volume_ratio": enriched.get("volume_ratio", ""),
            "atr_expansion_ratio": enriched.get("atr_expansion_ratio", ""),
            "candle_close_position": enriched.get("candle_close_position", ""),
            "rsi_14": enriched.get("rsi_14", ""),
            "macd": enriched.get("macd", ""),
            "macd_signal": enriched.get("macd_signal", ""),
            "macd_hist": enriched.get("macd_hist", ""),
            "whitelist_score": None,
            "regime": regime.regime.value if regime is not None else "",
            "executed": False,
            "result": "signal_logged",
            "exit_price": "",
            "exit_type": "",
            "pnl_pct": "",
            "leave_a_comment": "",
            "news_sources": "",
        }

    def _extract_signal_metadata(
        self,
        ohlcv: pd.DataFrame | None = None,
        ohlcv_1h: pd.DataFrame | None = None,
    ) -> dict:
        if ohlcv is None or ohlcv.empty:
            return {}
        try:
            from v12_strategy import compute_v12_15m

            df = ohlcv.copy().sort_values("timestamp").reset_index(drop=True)
            if ohlcv_1h is not None and not ohlcv_1h.empty:
                try:
                    from v12_strategy import align_1h_adx_to_15m

                    # Existing no-lookahead merge: each 15m row receives the
                    # ADX of the last 1H bar whose CLOSE time <= row time.
                    df = align_1h_adx_to_15m(df, ohlcv_1h)
                except Exception as exc:
                    logger.warning("V12 1H confirmation alignment failed: %s", exc)
            features = compute_v12_15m(df)
            row = features.iloc[-1]
            close = features["close"]
            volume_ma20 = features["volume"].rolling(20, min_periods=20).mean()
            atr_ma10 = features["atr"].rolling(10, min_periods=10).mean()

            delta = close.diff()
            gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, adjust=False).mean()
            rsi = 100 - 100 / (1 + gain / loss.replace(0, pd.NA))
            rsi = rsi.fillna(100.0)

            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            macd_signal = macd.ewm(span=9, adjust=False).mean()
            macd_hist = macd - macd_signal

            candle_range = float(row["high"] - row["low"])
            atr = float(row.get("atr", 0) or 0)
            return {
                "atr": atr,
                "adx_entry_tf": float(row.get("adx", 0) or 0),
                "adx_confirm_tf": float(row.get("adx_1h", row.get("adx", 0)) or 0),
                "volume_ratio": float(row["volume"] / volume_ma20.iloc[-1]) if pd.notna(volume_ma20.iloc[-1]) and volume_ma20.iloc[-1] else "",
                "atr_expansion_ratio": float(atr / atr_ma10.iloc[-1]) if pd.notna(atr_ma10.iloc[-1]) and atr_ma10.iloc[-1] else "",
                "candle_close_position": float((row["close"] - row["low"]) / (candle_range + 1e-9)),
                "rsi_14": float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else "",
                "macd": float(macd.iloc[-1]) if pd.notna(macd.iloc[-1]) else "",
                "macd_signal": float(macd_signal.iloc[-1]) if pd.notna(macd_signal.iloc[-1]) else "",
                "macd_hist": float(macd_hist.iloc[-1]) if pd.notna(macd_hist.iloc[-1]) else "",
            }
        except Exception as exc:
            logger.warning("V12 metadata enrichment failed: %s", exc)
            return {}

    async def _execute_signal(self, signal: Signal):
        result = await self.connectors["binance"].place_order(signal)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": signal.symbol,
            "strategy": signal.strategy_name,
            "side": signal.side,
            "price": result.avg_fill_price,
            "quantity": result.filled_qty,
            "status": result.status,
            "exchange": result.exchange,
            "confidence": signal.confidence,
            "fee_usdt": result.fee_usdt,
        }
        self._trade_log.append(entry)
        self._trade_log = self._trade_log[-100:]
        self.portfolio.trade_count_today += 1
        logger.info("ORDER %s", entry)

    async def _cleanup(self):
        for connector in self.connectors.values():
            await connector.close()
        logger.info("Engine shutdown complete")

    def get_status(self) -> dict:
        positions = list(self.portfolio.open_positions.values())
        drawdown = 0.0
        if self.portfolio.peak_capital:
            drawdown = (
                self.portfolio.peak_capital - self.portfolio.capital_usdt
            ) / self.portfolio.peak_capital

        return {
            "running": self.running,
            "halted": self.portfolio.is_halted,
            "halt_reason": self.portfolio.halt_reason,
            "capital_usdt": self.portfolio.capital_usdt,
            "peak_capital": self.portfolio.peak_capital,
            "total_pnl": self.portfolio.total_pnl,
            "daily_pnl": self.portfolio.daily_pnl,
            "drawdown_pct": drawdown,
            "open_positions": len(positions),
            "positions": deepcopy(positions),
            "trade_count_today": self.portfolio.trade_count_today,
            "regimes": {
                symbol: {
                    "regime": item[0].regime.value,
                    "confidence": item[0].confidence,
                    "strategies": item[0].recommended_strategies,
                    "adx": item[0].trend_strength,
                    "volatility": item[0].volatility,
                    "updated_at": datetime.fromtimestamp(item[1], timezone.utc).isoformat(),
                }
                for symbol, item in self._regime_cache.items()
            },
            "recent_trades": deepcopy((self._trade_log or self._signal_log)[-100:]),
            "metrics": {
                "win_rate": 0,
                "sharpe": 0,
                "signal_quality": 1.0 if self._signal_log else 0.0,
            },
            "strategy_allocation": {"v12_trend": 1.0},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


if __name__ == "__main__":
    engine = TradingEngine(ENGINE_CONFIG)
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        print("\nEngine stopped by user.")
