import asyncio

from config import BINANCE_API_KEY, BINANCE_API_SECRET
from core.exchange import ExchangeConnector


async def main():
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("Missing BINANCE_TESTNET_KEY or BINANCE_TESTNET_SECRET in .env")

    c = ExchangeConnector(
        exchange="binance",
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_API_SECRET,
        testnet=True,
    )
    try:
        ticker = await c.fetch_ticker("BTC/USDT:USDT")
        print(f"BTC price: {ticker.get('last', 'N/A')}")

        ob = await c.fetch_orderbook("BTC/USDT:USDT", depth=5)
        best_bid = ob["bids"][0][0] if ob.get("bids") else "N/A"
        best_ask = ob["asks"][0][0] if ob.get("asks") else "N/A"
        print(f"Best bid: {best_bid}  Best ask: {best_ask}")
    finally:
        await c.close()


asyncio.run(main())
