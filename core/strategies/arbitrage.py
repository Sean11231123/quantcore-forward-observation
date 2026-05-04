from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from core.strategies.base import BaseStrategy, Signal, StrategyConfig


@dataclass
class ArbitrageOpportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_pct: float
    net_profit_usdt: float
    quantity: float
    confidence: float


class ArbitrageStrategy(BaseStrategy):
    name = "arbitrage"

    def __init__(
        self,
        config: StrategyConfig,
        min_spread_pct: float = 0.003,
        maker_fee: float = 0.0002,
        taker_fee: float = 0.0005,
        slippage_buffer: float = 0.0005,
    ):
        super().__init__(config)
        self.min_spread_pct = min_spread_pct
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.slippage_buffer = slippage_buffer

    def find_opportunity(
        self,
        binance_orderbook: dict,
        okx_orderbook: dict,
        symbol: str,
    ) -> Optional[ArbitrageOpportunity]:
        if not binance_orderbook or not okx_orderbook:
            return None

        binance_ask = binance_orderbook["asks"][0][0]
        binance_bid = binance_orderbook["bids"][0][0]
        okx_ask = okx_orderbook["asks"][0][0]
        okx_bid = okx_orderbook["bids"][0][0]

        spread_a = (okx_bid - binance_ask) / binance_ask
        spread_b = (binance_bid - okx_ask) / okx_ask
        total_cost_pct = self.taker_fee * 2 + self.slippage_buffer

        best_scenario = None
        if spread_a > spread_b:
            net = spread_a - total_cost_pct
            if net > self.min_spread_pct:
                qty = min(
                    binance_orderbook["asks"][0][1],
                    okx_orderbook["bids"][0][1],
                    (self.config.capital_usdt * 0.1) / binance_ask,
                )
                best_scenario = ArbitrageOpportunity(
                    symbol=symbol,
                    buy_exchange="binance",
                    sell_exchange="okx",
                    buy_price=binance_ask,
                    sell_price=okx_bid,
                    spread_pct=spread_a,
                    net_profit_usdt=net * binance_ask * qty,
                    quantity=qty,
                    confidence=min(net / 0.01 + 0.5, 0.95),
                )
        else:
            net = spread_b - total_cost_pct
            if net > self.min_spread_pct:
                qty = min(
                    okx_orderbook["asks"][0][1],
                    binance_orderbook["bids"][0][1],
                    (self.config.capital_usdt * 0.1) / okx_ask,
                )
                best_scenario = ArbitrageOpportunity(
                    symbol=symbol,
                    buy_exchange="okx",
                    sell_exchange="binance",
                    buy_price=okx_ask,
                    sell_price=binance_bid,
                    spread_pct=spread_b,
                    net_profit_usdt=net * okx_ask * qty,
                    quantity=qty,
                    confidence=min(net / 0.01 + 0.5, 0.95),
                )

        return best_scenario

    def generate_signal(self, ohlcv: pd.DataFrame, orderbook=None) -> Optional[Signal]:
        return None
