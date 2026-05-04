import asyncio

from config import OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE
from core.exchange import ExchangeConnector


async def main():
    c = ExchangeConnector(
        exchange="okx",
        api_key=OKX_API_KEY,
        api_secret=OKX_API_SECRET,
        passphrase=OKX_PASSPHRASE,
        testnet=True,
    )
    try:
        ob = await c.fetch_orderbook("BTC/USDT:USDT", depth=5)
        best_bid = ob["bids"][0][0] if ob.get("bids") else "N/A"
        best_ask = ob["asks"][0][0] if ob.get("asks") else "N/A"
        print(f"OKX best bid: {best_bid}")
        print(f"OKX best ask: {best_ask}")
    finally:
        await c.close()


asyncio.run(main())
