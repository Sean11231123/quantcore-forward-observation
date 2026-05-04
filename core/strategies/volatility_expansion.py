from __future__ import annotations

from typing import Optional

import pandas as pd

from core.strategies.base import BaseStrategy, Signal, StrategyConfig


class VolatilityExpansionStrategy(BaseStrategy):
    name = "volatility_expansion"

    def __init__(
        self,
        config: StrategyConfig,
        bb_period: int = 20,
        bb_expansion_thresh: float = 0.20,
        atr_period: int = 14,
        vol_lookback: int = 10,
        atr_sl_mult: float = 1.0,
        time_stop_bars: int = 8,
    ):
        super().__init__(config)
        self.bb_period = bb_period
        self.bb_expansion_thresh = bb_expansion_thresh
        self.atr_period = atr_period
        self.vol_lookback = vol_lookback
        self.atr_sl_mult = atr_sl_mult
        self.time_stop_bars = time_stop_bars

    def generate_signal(self, ohlcv: pd.DataFrame, **kwargs) -> Optional[Signal]:
        if len(ohlcv) < max(self.bb_period, self.atr_period) + self.vol_lookback + 5:
            return None

        close = ohlcv["close"]
        high = ohlcv["high"]
        low = ohlcv["low"]
        volume = ohlcv["volume"]

        bb_mid = close.rolling(self.bb_period).mean()
        bb_std = close.rolling(self.bb_period).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = (bb_upper - bb_lower) / bb_mid

        atr = self._atr(high, low, close)
        atr_ma = atr.rolling(self.vol_lookback).mean()
        volume_ma = volume.rolling(self.vol_lookback).mean()

        current_width = bb_width.iloc[-1]
        min_width = bb_width.tail(self.vol_lookback + 1).iloc[:-1].min()
        curr_atr = atr.iloc[-1]
        price = close.iloc[-1]

        if any(pd.isna(v) for v in [current_width, min_width, curr_atr, atr_ma.iloc[-1]]):
            return None

        bb_expansion = current_width > min_width * (1 + self.bb_expansion_thresh)
        atr_expansion = curr_atr > atr_ma.iloc[-1] * 1.1
        volume_expansion = volume.iloc[-1] > volume_ma.iloc[-1] if pd.notna(volume_ma.iloc[-1]) else True
        if not (bb_expansion and atr_expansion and volume_expansion):
            return None

        expansion_ratio = current_width / min_width if min_width else 1.0
        confidence = min(0.95, max(0.6, 0.6 + (expansion_ratio - 1) * 0.5))
        width_target = price * current_width * 1.5

        if price > bb_upper.iloc[-1]:
            stop = bb_mid.iloc[-1]
            target = price + width_target
            qty = self._position_size(price, stop)
            return Signal(
                strategy_name=self.name,
                symbol=self.config.symbol,
                side="buy",
                order_type="limit",
                price=price,
                quantity=qty,
                stop_loss=stop,
                take_profit=target,
                confidence=confidence,
                metadata={
                    "bb_width": current_width,
                    "atr": curr_atr,
                    "time_stop_bars": self.time_stop_bars,
                },
            )

        if price < bb_lower.iloc[-1]:
            stop = bb_mid.iloc[-1]
            target = price - width_target
            qty = self._position_size(price, stop)
            return Signal(
                strategy_name=self.name,
                symbol=self.config.symbol,
                side="sell",
                order_type="limit",
                price=price,
                quantity=qty,
                stop_loss=stop,
                take_profit=target,
                confidence=confidence,
                metadata={
                    "bb_width": current_width,
                    "atr": curr_atr,
                    "time_stop_bars": self.time_stop_bars,
                },
            )

        return None

    def _atr(self, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        tr = pd.concat(
            [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
            axis=1,
        ).max(axis=1)
        return tr.rolling(self.atr_period).mean()
