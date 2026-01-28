from coinbase.rest import RESTClient as CoinbaseClient
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.values import Price, Amount
from domain.entities import Symbol
from dotenv import load_dotenv
import os

load_dotenv()

class CoinbaseRegularAdapter:
    def __init__(self):
        api_key = os.getenv('COINBASE_API_KEY')
        api_secret = os.getenv('COINBASE_API_SECRET')
        self.client = CoinbaseClient(api_key=api_key, api_secret=api_secret)

    def get_name(self) -> str:
        return "coinbase"

    def fetch_fees(self) -> Dict[str, Any]:
        """Fetch standardized fee structure for Coinbase Regular."""
        try:
            summary = self.client.get_transaction_summary()
            return {
                'maker': Decimal(str(getattr(summary, 'maker_fee_rate', '0.004'))),
                'taker': Decimal(str(getattr(summary, 'taker_fee_rate', '0.006'))),
                'bnb_discount': False,
                'raw': summary
            }
        except:
            return {
                'maker': Decimal('0.004'),
                'taker': Decimal('0.006'),
                'bnb_discount': False,
                'raw': {}
            }

    def get_balance(self, asset: str) -> Decimal:
        accounts = self.client.get_accounts()
        for acc in accounts.accounts:
            if acc.currency == asset.upper():
                return Decimal(acc.available_balance.value)
        return Decimal('0')

    def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict[str, List[Dict[str, Decimal]]]:
        product_id = str(symbol).replace('/', '-')
        book = self.client.get_product_book(product_id=product_id, limit=limit)
        return {
            'bids': [{'price': Decimal(p.price), 'amount': Decimal(p.size)} for p in book.pricebook.bids],
            'asks': [{'price': Decimal(p.price), 'amount': Decimal(p.size)} for p in book.pricebook.asks]
        }

    def get_ticker_price(self, symbol: Symbol) -> Price:
        product_id = str(symbol).replace('/', '-')
        ticker = self.client.get_product(product_id=product_id)
        return Price(Decimal(ticker.price))

    def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict:
        product_id = str(symbol).replace('/', '-')
        order_type = 'LIMIT_ORDER' if price else 'MARKET_ORDER'
        params = {
            'product_id': product_id,
            'side': side.upper(),
            'base_size': str(amount)
        }
        if price:
            params['limit_price'] = str(price)
        return self.client.place_order(order_configuration={order_type.lower(): params})

    def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        try:
            self.client.cancel_order(order_id)
            return True
        except:
            return False

    def stake(self, asset: str, amount: Decimal) -> Dict:
        """Staking not supported on legacy Wallet API."""
        return {'success': False, 'error': 'Not supported'}

    def unstake(self, asset: str, amount: Decimal) -> Dict:
        """Staking not supported on legacy Wallet API."""
        return {'success': False, 'error': 'Not supported'}

    def get_staking_assets(self) -> List[Dict]:
        """Staking not supported on legacy Wallet API."""
        return []