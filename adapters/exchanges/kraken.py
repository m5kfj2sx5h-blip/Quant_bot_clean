import krakenex
from decimal import Decimal
from typing import Dict, List, Any, Optional
from exchanges.base import ExchangeAdapter
from domain.values import Price, Amount, Symbol         #<------- NEEDS FIXING!

class KrakenAdapter(ExchangeAdapter):
    def __init__(self, config: Dict[str, Any]):
        self.client = krakenex.API(key=config['api_key'], secret=config['api_secret'])

    def get_name(self) -> str:
        return "kraken"

    async def get_balance(self, asset: str) -> Decimal:
        balance = self.client.query_private('Balance')
        return Decimal(balance['result'].get(asset.upper(), '0'))

    async def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict[str, List[Dict[str, Decimal]]]:
        book = self.client.query_public('Depth', {'pair': str(symbol).replace('/', ''), 'count': limit})
        pair_key = list(book['result'].keys())[0]
        return {
            'bids': [{ 'price': Decimal(p[0]), 'amount': Decimal(p[1]) } for p in book['result'][pair_key]['bids']],
            'asks': [{ 'price': Decimal(p[0]), 'amount': Decimal(p[1]) } for p in book['result'][pair_key]['asks']]
        }

    async def get_ticker_price(self, symbol: Symbol) -> Price:
        ticker = self.client.query_public('Ticker', {'pair': str(symbol).replace('/', '')})
        pair_key = list(ticker['result'].keys())[0]
        return Price(Decimal(ticker['result'][pair_key]['c'][0]))

    async def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict:
        order_type = 'limit' if price else 'market'
        resp = self.client.query_private('AddOrder', {
            'pair': str(symbol).replace('/', ''),
            'type': side,
            'ordertype': order_type,
            'volume': str(amount),
            'price': str(price) if price else None
        })
        return {'id': resp['result']['txid'][0] if 'txid' in resp['result'] else None}

    async def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        resp = self.client.query_private('CancelOrder', {'txid': order_id})
        return 'result' in resp and resp['result'].get('count', 0) > 0

    def get_supported_pairs(self) -> List[Symbol]:
        pairs = self.client.query_public('AssetPairs')['result']
        return [Symbol(key.replace('XXBT', 'BTC').replace('XETH', 'ETH').replace('ZUSD', 'USD').replace('.', '/')) for key in pairs.keys()]  # Includes USDT/USDC if supported