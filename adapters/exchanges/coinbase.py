import ccxt.async_support as ccxt
from decimal import Decimal
from typing import Dict, List, Any, Optional
from exchanges.base import ExchangeAdapter
from domain.values import Price, Amount, Symbol

class CoinbaseRegularAdapter(ExchangeAdapter):
    def __init__(self, config: Dict[str, Any]):
        self.client = ccxt.coinbase({
            'apiKey': config['api_key'],
            'secret': config['api_secret'],
            'enableRateLimit': True
        })

    def get_name(self) -> str:
        return "coinbase"

    async def get_balance(self, asset: str) -> Decimal:
        balance = await self.client.fetch_balance()
        return Decimal(balance.get(asset.upper(), {}).get('free', '0'))

    async def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict[str, List[Dict[str, Decimal]]]:
        book = await self.client.fetch_order_book(str(symbol).replace('/', '-'), limit)
        return {
            'bids': [{ 'price': Decimal(p[0]), 'amount': Decimal(p[1]) } for p in book['bids']],
            'asks': [{ 'price': Decimal(p[0]), 'amount': Decimal(p[1]) } for p in book['asks']]
        }

    async def get_ticker_price(self, symbol: Symbol) -> Price:
        ticker = await self.client.fetch_ticker(str(symbol).replace('/', '-'))
        return Price(Decimal(ticker['last']))

    async def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict:
        # Preserve zero-fee for Coinbase One (<$500/month orders)
        params = {'client_order_id': f"{side}_{str(symbol)}_{datetime.now().isoformat()}"}
        return await self.client.create_order(
            str(symbol).replace('/', '-'), 'limit' if price else 'market', side, float(amount), float(price) if price else None, params
        )

    async def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        try:
            await self.client.cancel_order(order_id, str(symbol).replace('/', '-'))
            return True
        except:
            return False

    def get_supported_pairs(self) -> List[Symbol]:
        markets = self.client.load_markets()
        return [Symbol(pair.replace('-', '/')) for pair in markets if 'USDT' in pair or 'USDC' in pair or 'USD' in pair]  # Prioritizes USDT/USDC