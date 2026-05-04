from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from core.strategies.base import BaseStrategy, Signal, StrategyConfig


@dataclass
class MarketMakingQuote:
    bid_price: float
    ask_price: float
    bid_qty: float
    ask_qty: float
    mid_price: float
    spread: float
    reservation_price: float
    skew: float


class MarketMakingStrategy(BaseStrategy):
    name = "market_making"

    def __init__(
        self,
        config: StrategyConfig,
        gamma: float = 0.1,
        sigma: float = 0.02,
        k: float = 1.5,
        T: float = 1.0,
        max_inventory: float = 0.5,
        min_spread_pct: float = 0.002,
    ):
        super().__init__(config)
        self.gamma = gamma
        self.sigma = sigma
        self.k = k
        self.T = T
        self.max_inventory = max_inventory
        self.min_spread_pct = min_spread_pct
        self.inventory = 0.0

    def compute_quotes(
        self,
        mid_price: float,
        inventory: float,
        t: float,
        realized_vol: float,
    ) -> MarketMakingQuote:
        sigma = max(realized_vol, self.sigma)
        tau = max(self.T - t, 0.001)

        reservation_price = mid_price - inventory * self.gamma * sigma**2 * tau
        base_spread = self.gamma * sigma**2 * tau
        liquidity_spread = (2 / self.gamma) * np.log(1 + self.gamma / self.k)
        optimal_spread = base_spread + liquidity_spread
        optimal_spread = max(optimal_spread, self.min_spread_pct * mid_price)

        bid = reservation_price - optimal_spread / 2
        ask = reservation_price + optimal_spread / 2

        inv_ratio = inventory / (self.config.capital_usdt * self.max_inventory / mid_price)
        skew = float(np.clip(inv_ratio, -1, 1))

        base_qty = (self.config.capital_usdt * 0.05) / mid_price
        bid_qty = base_qty * (1 - max(skew, 0))
        ask_qty = base_qty * (1 + min(skew, 0))

        return MarketMakingQuote(
            bid_price=round(bid, 2),
            ask_price=round(ask, 2),
            bid_qty=max(bid_qty, 0),
            ask_qty=max(ask_qty, 0),
            mid_price=mid_price,
            spread=optimal_spread,
            reservation_price=reservation_price,
            skew=skew,
        )

    def generate_signal(self, ohlcv: pd.DataFrame, orderbook=None) -> Optional[Signal]:
        return None
