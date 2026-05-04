from __future__ import annotations

from typing import Optional

import pandas as pd

from core.strategies.base import BaseStrategy, Signal, StrategyConfig


class TrendFollowingStrategy(BaseStrategy):
    name = "trend_following"

    def __init__(
        self,
        config: StrategyConfig,
        fast_ema: int = 12,
        slow_ema: int = 26,
        signal_ema: int = 9,
        atr_sl_mult: float = 2.0,
        atr_tp_mult: float = 3.0,
    ):
        super().__init__(config)
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.signal_ema = signal_ema
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult

    def generate_signal(self, ohlcv: pd.DataFrame, orderbook=None) -> Optional[Signal]:
        close = ohlcv["close"]
        high, low = ohlcv["high"], ohlcv["low"]

        ema_fast = close.ewm(span=self.fast_ema, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_ema, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=self.signal_ema, adjust=False).mean()
        macd_hist = macd - macd_signal

        tr = pd.concat(
            [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        prev_hist = macd_hist.iloc[-2]
        curr_hist = macd_hist.iloc[-1]
        price = close.iloc[-1]

        if prev_hist < 0 and curr_hist > 0 and ema_fast.iloc[-1] > ema_slow.iloc[-1]:
            sl = price - self.atr_sl_mult * atr
            tp = price + self.atr_tp_mult * atr
            qty = self._position_size(price, sl)
            return Signal(
                strategy_name=self.name,
                symbol=self.config.symbol,
                side="buy",
                order_type="limit",
                price=price,
                quantity=qty,
                stop_loss=sl,
                take_profit=tp,
                confidence=min(abs(curr_hist) / atr + 0.5, 0.95),
                metadata={"macd": curr_hist, "atr": atr},
            )

        if prev_hist > 0 and curr_hist < 0 and ema_fast.iloc[-1] < ema_slow.iloc[-1]:
            sl = price + self.atr_sl_mult * atr
            tp = price - self.atr_tp_mult * atr
            qty = self._position_size(price, sl)
            return Signal(
                strategy_name=self.name,
                symbol=self.config.symbol,
                side="sell",
                order_type="limit",
                price=price,
                quantity=qty,
                stop_loss=sl,
                take_profit=tp,
                confidence=min(abs(curr_hist) / atr + 0.5, 0.95),
                metadata={"macd": curr_hist, "atr": atr},
            )

        return None
