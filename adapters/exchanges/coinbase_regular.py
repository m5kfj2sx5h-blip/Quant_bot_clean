from coinbase.wallet.client import Client as CoinbaseClient
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.entities import Price, Amount, Symbol
from dotenv import load_dotenv
import os

load_dotenv()

class CoinbaseRegularAdapter:
    def __init__(self):
        api_key = os.getenv('COINBASE_API_KEY')
        api_secret = os.getenv('COINBASE_API_SECRET')
        self.client = CoinbaseClient(api_key, api_secret)

    def get_name(self) -> str:
        return "coinbase"

    def get_balance(self, asset: str) -> Decimal:
        accounts = self.client.get_accounts()
        for acc in accounts.data:
            if acc.currency == asset.upper():
                return Decimal(acc.balance.amount)
        return Decimal('0')

    def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict[str, List[Dict[str, Decimal]]]:
        product_id = str(symbol).replace('/', '-')
        book = self.client.get_product_order_book(product_id, level=2)
        return {
            'bids': [{'price': Decimal(p[0]), 'amount': Decimal(p[1])} for p in book['bids'][:limit]],
            'asks': [{'price': Decimal(p[0]), 'amount': Decimal(p[1])} for p in book['asks'][:limit]]
        }

    def get_ticker_price(self, symbol: Symbol) -> Price:
        product_id = str(symbol).replace('/', '-')
        ticker = self.client.get_product_ticker(product_id)
        return Price(Decimal(ticker['price']))

    def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict:
        product_id = str(symbol).replace('/', '-')
        params = {
            'product_id': product_id,
            'side': side,
            'funds': str(amount) if not price else None,
            'size': str(amount) if price else None,
            'price': str(price) if price else None,
            'type': 'limit' if price else 'market'
        }
        return self.client.place_order(**params)

    def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        try:
            self.client.cancel_order(order_id)
            return True
        except:
            return False

    def get_supported_pairs(self) -> List[Symbol]:
        products = self.client.get_products()
        return [Symbol(p['base_currency'] + '/' + p['quote_currency']) for p in products if 'USDT' in p['quote_currency'] or 'USDC' in p['quote_currency'] or 'USD' in p['quote_currency']]