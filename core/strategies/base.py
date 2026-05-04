from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd


OrderSide = Literal["buy", "sell"]
OrderType = Literal["limit", "market"]


@dataclass
class Signal:
    strategy_name: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Optional[float]
    quantity: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    confidence: float
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class StrategyConfig:
    symbol: str
    exchange: str
    capital_usdt: float
    max_position_pct: float = 0.20
    risk_per_trade_pct: float = 0.01


class BaseStrategy(ABC):
    name: str

    def __init__(self, config: StrategyConfig):
        self.config = config

    @abstractmethod
    def generate_signal(self, ohlcv: pd.DataFrame, orderbook: Optional[dict] = None) -> Optional[Signal]:
        """Return a signal or None when there is no trade opportunity."""

    def _position_size(self, entry: float, stop: float) -> float:
        risk_usdt = self.config.capital_usdt * self.config.risk_per_trade_pct
        risk_per_unit = abs(entry - stop)
        if risk_per_unit == 0:
            return 0.0

        qty = risk_usdt / risk_per_unit
        max_qty = (self.config.capital_usdt * self.config.max_position_pct) / entry
        return min(qty, max_qty)
