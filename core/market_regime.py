"""
Layer 1: Market Regime Detector
Identifies current market condition to route to appropriate strategy
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MarketRegime(Enum):
    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    BREAKOUT = "breakout"
    CHOPPY = "choppy"


@dataclass
class RegimeSignal:
    regime: MarketRegime
    confidence: float          # 0.0 ~ 1.0
    volatility: float          # Realized volatility (annualized)
    trend_strength: float      # ADX value
    mean_reversion_score: float  # Hurst exponent proximity to 0.5
    recommended_strategies: list[str]
    metadata: dict


class MarketRegimeDetector:
    """
    Multi-indicator regime detection engine.
    Combines ADX, Hurst Exponent, ATR, and Bollinger Band width
    to classify market condition and route strategies.
    """

    def __init__(
        self,
        adx_period: int = 14,
        atr_period: int = 14,
        bb_period: int = 20,
        hurst_window: int = 100,
        vol_lookback: int = 30,
    ):
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.bb_period = bb_period
        self.hurst_window = hurst_window
        self.vol_lookback = vol_lookback

    def detect(self, ohlcv: pd.DataFrame) -> RegimeSignal:
        """
        Main entry: pass OHLCV DataFrame, receive RegimeSignal.
        ohlcv columns: open, high, low, close, volume
        """
        close = ohlcv["close"]
        high = ohlcv["high"]
        low = ohlcv["low"]

        adx, plus_di, minus_di = self._compute_adx(high, low, close)
        atr = self._compute_atr(high, low, close)
        bb_width = self._compute_bb_width(close)
        hurst = self._compute_hurst(close)
        realized_vol = self._compute_realized_vol(close)

        current_adx = adx.iloc[-1]
        current_atr = atr.iloc[-1]
        current_bb = bb_width.iloc[-1]
        current_hurst = hurst
        current_vol = realized_vol
        trend_up = plus_di.iloc[-1] > minus_di.iloc[-1]

        regime, confidence, strategies = self._classify(
            current_adx, current_bb, current_hurst, current_vol, trend_up
        )

        return RegimeSignal(
            regime=regime,
            confidence=confidence,
            volatility=current_vol,
            trend_strength=current_adx,
            mean_reversion_score=abs(current_hurst - 0.5),
            recommended_strategies=strategies,
            metadata={
                "adx": current_adx,
                "atr": current_atr,
                "bb_width": current_bb,
                "hurst": current_hurst,
                "plus_di": plus_di.iloc[-1],
                "minus_di": minus_di.iloc[-1],
            },
        )

    def _classify(
        self,
        adx: float,
        bb_width: float,
        hurst: float,
        vol: float,
        trend_up: bool,
    ) -> tuple[MarketRegime, float, list[str]]:
        # Choppy: weak trend, persistent noisy movement, and compressed bands.
        if adx < 20 and hurst > 0.50 and bb_width < 0.025:
            return MarketRegime.CHOPPY, 0.75, []

        # Strong trend
        if adx > 30:
            regime = MarketRegime.TRENDING_BULL if trend_up else MarketRegime.TRENDING_BEAR
            strategies = ["trend_following"]
            confidence = min((adx - 30) / 20 + 0.6, 1.0)
        # Breakout detection: BB width expanding + ADX starting to rise
        elif bb_width > 0.04 and adx > 20:
            regime = MarketRegime.BREAKOUT
            strategies = ["trend_following", "momentum"]
            confidence = 0.65
        # High volatility ranging
        elif vol > 0.8 and adx < 20:
            regime = MarketRegime.HIGH_VOLATILITY
            strategies = ["market_making"]
            confidence = 0.70
        # Low volatility with mean-reversion tendency
        elif hurst < 0.45 and adx < 20:
            regime = MarketRegime.RANGING
            strategies = ["mean_reversion", "market_making", "arbitrage"]
            confidence = min((0.5 - hurst) / 0.1 + 0.5, 0.9)
        # Low vol quiet market
        elif vol < 0.4 and adx < 20:
            regime = MarketRegime.LOW_VOLATILITY
            strategies = ["arbitrage", "market_making"]
            confidence = 0.60
        else:
            regime = MarketRegime.RANGING
            strategies = ["mean_reversion", "arbitrage"]
            confidence = 0.50

        return regime, confidence, strategies

    # ── Technical Indicators ──────────────────────────────────────────────

    def _compute_adx(
        self, high: pd.Series, low: pd.Series, close: pd.Series
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        p = self.adx_period
        tr = pd.concat(
            [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
            axis=1,
        ).max(axis=1)
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        plus_dm[plus_dm < (-low.diff()).clip(lower=0)] = 0
        minus_dm[minus_dm < high.diff().clip(lower=0)] = 0

        atr = tr.ewm(span=p, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(span=p, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(span=p, adjust=False).mean() / atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.ewm(span=p, adjust=False).mean()
        return adx, plus_di, minus_di

    def _compute_atr(
        self, high: pd.Series, low: pd.Series, close: pd.Series
    ) -> pd.Series:
        tr = pd.concat(
            [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
            axis=1,
        ).max(axis=1)
        return tr.rolling(self.atr_period).mean()

    def _compute_bb_width(self, close: pd.Series) -> pd.Series:
        ma = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        return (2 * std) / ma  # Normalized BB width

    def _compute_hurst(self, close: pd.Series) -> float:
        """Hurst exponent via R/S analysis. <0.5 mean-reverting, >0.5 trending."""
        series = close.iloc[-self.hurst_window:].values
        n = len(series)
        if n < 20:
            return 0.5
        lags = range(2, min(n // 2, 20))
        rs_vals = []
        for lag in lags:
            chunks = [series[i:i+lag] for i in range(0, n - lag + 1, lag)]
            rs_chunk = []
            for chunk in chunks:
                if len(chunk) < 2:
                    continue
                mean_c = np.mean(chunk)
                dev = np.cumsum(chunk - mean_c)
                r = dev.max() - dev.min()
                s = np.std(chunk, ddof=1)
                if s > 0:
                    rs_chunk.append(r / s)
            if rs_chunk:
                rs_vals.append((lag, np.mean(rs_chunk)))
        if len(rs_vals) < 2:
            return 0.5
        lags_log = np.log([x[0] for x in rs_vals])
        rs_log = np.log([x[1] for x in rs_vals])
        hurst = np.polyfit(lags_log, rs_log, 1)[0]
        return float(np.clip(hurst, 0.1, 0.9))

    def _compute_realized_vol(self, close: pd.Series) -> float:
        """Annualized realized volatility."""
        returns = np.log(close / close.shift()).dropna()
        return float(returns.iloc[-self.vol_lookback:].std() * np.sqrt(365 * 24))
