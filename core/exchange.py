"""
Layer 5: Exchange Connector (Binance + OKX unified interface)

"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, Literal
import numpy as np

from core.strategies.base import Signal

# ─────────────────────────────────────────────────────────────────────────────
# Layer 5: Exchange Connector (Unified interface for Binance + OKX)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OrderResult:
    order_id: str
    exchange: str
    symbol: str
    side: str
    price: float
    quantity: float
    status: str  # "filled" | "partial" | "rejected" | "open"
    filled_qty: float
    avg_fill_price: float
    fee_usdt: float
    timestamp: float = field(default_factory=time.time)


class ExchangeConnector:
    """
    Unified async connector for Binance + OKX Futures (Perp).
    Install: pip install ccxt
    
    Usage:
        connector = ExchangeConnector(
            exchange="binance",
            api_key="...",
            api_secret="...",
            testnet=True
        )
        await connector.place_order(signal)
    """

    def __init__(
        self,
        exchange: Literal["binance", "okx"],
        api_key: str,
        api_secret: str,
        passphrase: str = "",  # OKX only
        testnet: bool = True,
    ):
        self.exchange_name = exchange
        self.testnet = testnet
        self._client = None
        self._init_client(api_key, api_secret, passphrase)

    def _init_client(self, api_key: str, api_secret: str, passphrase: str):
        """Initialize ccxt exchange client."""
        try:
            import ccxt.async_support as ccxt

            common_config = {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }

            if self.exchange_name == "binance":
                self._client = ccxt.binance(common_config)
                if self.testnet:
                    self._client.set_sandbox_mode(True)
                    self._client.urls["api"]["public"] = "https://testnet.binancefuture.com"
                    self._client.urls["api"]["private"] = "https://testnet.binancefuture.com"

            elif self.exchange_name == "okx":
                common_config["password"] = passphrase
                common_config["options"]["fetchCurrencies"] = False
                if self.testnet:
                    common_config["headers"] = {"x-simulated-trading": "1"}
                self._client = ccxt.okx(common_config)
                self._client.has["fetchCurrencies"] = False
                if self.testnet:
                    self._client.urls["api"] = self._client.urls.get("test", self._client.urls["api"])

        except ImportError:
            print("[WARNING] ccxt not installed. Run: pip install ccxt")
            self._client = None

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1h", limit: int = 200
    ) -> list:
        """Fetch OHLCV candles. Returns list of [ts, open, high, low, close, vol]."""
        if not self._client:
            return []
        return await self._client.fetch_ohlcv(symbol, timeframe, limit=limit)

    async def fetch_orderbook(self, symbol: str, depth: int = 10) -> dict:
        """Fetch order book. Returns {bids: [[price,qty],...], asks: [[price,qty],...]}"""
        if not self._client:
            return {}
        return await self._client.fetch_order_book(symbol, limit=depth)

    async def fetch_ticker(self, symbol: str) -> dict:
        if not self._client:
            return {}
        return await self._client.fetch_ticker(symbol)

    async def place_order(self, signal: Signal) -> OrderResult:
        """Convert Signal to exchange order. Returns OrderResult."""
        if not self._client:
            # Simulation mode
            return OrderResult(
                order_id=f"SIM_{int(time.time())}",
                exchange=self.exchange_name,
                symbol=signal.symbol,
                side=signal.side,
                price=signal.price or 0,
                quantity=signal.quantity,
                status="filled",
                filled_qty=signal.quantity,
                avg_fill_price=signal.price or 0,
                fee_usdt=signal.quantity * (signal.price or 0) * 0.0005,
            )

        try:
            order_type = "limit" if signal.price else "market"
            result = await self._client.create_order(
                symbol=signal.symbol,
                type=order_type,
                side=signal.side,
                amount=signal.quantity,
                price=signal.price,
            )

            # Set stop-loss and take-profit orders
            if signal.stop_loss:
                await self._place_sl_tp(signal, result["id"])

            return OrderResult(
                order_id=result["id"],
                exchange=self.exchange_name,
                symbol=signal.symbol,
                side=signal.side,
                price=result.get("price", 0),
                quantity=signal.quantity,
                status=result.get("status", "open"),
                filled_qty=result.get("filled", 0),
                avg_fill_price=result.get("average", 0) or result.get("price", 0),
                fee_usdt=result.get("fee", {}).get("cost", 0),
            )

        except Exception as e:
            return OrderResult(
                order_id="ERROR",
                exchange=self.exchange_name,
                symbol=signal.symbol,
                side=signal.side,
                price=signal.price or 0,
                quantity=signal.quantity,
                status="rejected",
                filled_qty=0,
                avg_fill_price=0,
                fee_usdt=0,
            )

    async def _place_sl_tp(self, signal: Signal, parent_order_id: str):
        """Place stop-loss and take-profit orders after parent fill."""
        close_side = "sell" if signal.side == "buy" else "buy"
        if signal.stop_loss:
            await self._client.create_order(
                symbol=signal.symbol,
                type="stop_market",
                side=close_side,
                amount=signal.quantity,
                params={"stopPrice": signal.stop_loss, "reduceOnly": True},
            )
        if signal.take_profit:
            await self._client.create_order(
                symbol=signal.symbol,
                type="take_profit_market",
                side=close_side,
                amount=signal.quantity,
                params={"stopPrice": signal.take_profit, "reduceOnly": True},
            )

    async def close(self):
        if self._client:
            await self._client.close()
