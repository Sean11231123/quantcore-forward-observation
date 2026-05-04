from __future__ import annotations

from typing import Optional

import pandas as pd

from core.strategies.base import BaseStrategy, Signal, StrategyConfig


class PullbackStrategy(BaseStrategy):
    name = "pullback"

    def __init__(
        self,
        config: StrategyConfig,
        ema_period: int = 20,
        rsi_period: int = 14,
        rsi_long_thresh: float = 45,
        rsi_short_thresh: float = 55,
        atr_sl_mult: float = 1.5,
        atr_tp_mult: float = 2.5,
    ):
        super().__init__(config)
        self.ema_period = ema_period
        self.rsi_period = rsi_period
        self.rsi_long_thresh = rsi_long_thresh
        self.rsi_short_thresh = rsi_short_thresh
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult

    def generate_signal(self, ohlcv: pd.DataFrame, regime=None, **kwargs) -> Optional[Signal]:
        if len(ohlcv) < 60:
            return None

        close = ohlcv["close"]
        high = ohlcv["high"]
        low = ohlcv["low"]

        ema20 = close.ewm(span=self.ema_period, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        rsi = self._rsi(close)
        atr = self._atr(high, low, close)
        atr_ma = atr.rolling(20).mean()

        price = close.iloc[-1]
        curr_atr = atr.iloc[-1]
        if pd.isna(curr_atr) or curr_atr <= 0:
            return None

        atr_expansion = curr_atr > atr_ma.iloc[-1] * 1.15 if pd.notna(atr_ma.iloc[-1]) else False
        if atr_expansion:
            return None

        curr_rsi = rsi.iloc[-1]
        confidence = min(0.9, max(0.6, 0.6 + abs(curr_rsi - 50) / 100))

        if (
            price > ema50.iloc[-1]
            and low.iloc[-1] <= ema20.iloc[-1]
            and price > ema20.iloc[-1]
            and curr_rsi > self.rsi_long_thresh
        ):
            stop = low.tail(3).min() - 0.5 * curr_atr
            target = high.rolling(20).max().shift(1).iloc[-1]
            if pd.isna(target) or target <= price:
                target = price + self.atr_tp_mult * curr_atr
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
                metadata={"rsi": curr_rsi, "atr": curr_atr, "ema20": ema20.iloc[-1]},
            )

        if (
            price < ema50.iloc[-1]
            and high.iloc[-1] >= ema20.iloc[-1]
            and price < ema20.iloc[-1]
            and curr_rsi < self.rsi_short_thresh
        ):
            stop = high.tail(3).max() + 0.5 * curr_atr
            target = low.rolling(20).min().shift(1).iloc[-1]
            if pd.isna(target) or target >= price:
                target = price - self.atr_tp_mult * curr_atr
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
                metadata={"rsi": curr_rsi, "atr": curr_atr, "ema20": ema20.iloc[-1]},
            )

        return None

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs = gain / loss.replace(0, pd.NA)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        tr = pd.concat(
            [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
            axis=1,
        ).max(axis=1)
        return tr.rolling(14).mean()
