from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from core.strategies.base import BaseStrategy, Signal, StrategyConfig


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(
        self,
        config: StrategyConfig,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 35,
        rsi_overbought: float = 65,
        zscore_threshold: float = 2.0,
    ):
        super().__init__(config)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.zscore_threshold = zscore_threshold

    def generate_signal(self, ohlcv: pd.DataFrame, orderbook=None) -> Optional[Signal]:
        close = ohlcv["close"]

        ma = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        upper = ma + self.bb_std * std
        lower = ma - self.bb_std * std
        zscore = (close - ma) / std

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs = gain / loss.replace(0, np.inf)
        rsi = 100 - (100 / (1 + rs))

        price = close.iloc[-1]
        z = zscore.iloc[-1]
        r = rsi.iloc[-1]
        mid = ma.iloc[-1]
        atr = std.iloc[-1]

        if z < -self.zscore_threshold and r < self.rsi_oversold:
            sl = price - 1.5 * atr
            tp = mid
            qty = self._position_size(price, sl)
            return Signal(
                strategy_name=self.name,
                symbol=self.config.symbol,
                side="buy",
                order_type="limit",
                price=lower.iloc[-1],
                quantity=qty,
                stop_loss=sl,
                take_profit=tp,
                confidence=min(abs(z) / 3 * 0.8, 0.90),
                metadata={"zscore": z, "rsi": r, "bb_lower": lower.iloc[-1]},
            )

        if z > self.zscore_threshold and r > self.rsi_overbought:
            sl = price + 1.5 * atr
            tp = mid
            qty = self._position_size(price, sl)
            return Signal(
                strategy_name=self.name,
                symbol=self.config.symbol,
                side="sell",
                order_type="limit",
                price=upper.iloc[-1],
                quantity=qty,
                stop_loss=sl,
                take_profit=tp,
                confidence=min(abs(z) / 3 * 0.8, 0.90),
                metadata={"zscore": z, "rsi": r, "bb_upper": upper.iloc[-1]},
            )

        return None
