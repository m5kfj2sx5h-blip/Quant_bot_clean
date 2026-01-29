from coinbase.rest import RESTClient as CoinbaseClient
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.values import Price, Amount
from domain.entities import Symbol
from dotenv import load_dotenv
import os

load_dotenv('config/.env')

class CoinbaseRegularAdapter:
    def __init__(self):
        api_key = os.getenv('COINBASE_KEY')
        api_secret = os.getenv('COINBASE_SECRET')
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

    def get_balance(self, asset: Optional[str] = None) -> Any:
        """Fetch balance for one or all assets."""
        try:
            response = self.client.get_accounts()
            accounts = getattr(response, 'accounts', [])
            
            if asset:
                for acc in accounts:
                    currency = getattr(acc, 'currency', acc.get('currency') if isinstance(acc, dict) else None)
                    if currency == asset.upper():
                        bal = getattr(acc, 'available_balance', acc.get('available_balance') if isinstance(acc, dict) else None)
                        if isinstance(bal, dict):
                            return Decimal(str(bal.get('value', '0')))
                        return Decimal(str(getattr(bal, 'value', '0')))
                return Decimal('0')
            else:
                balances = {}
                for acc in accounts:
                    currency = getattr(acc, 'currency', acc.get('currency') if isinstance(acc, dict) else None)
                    bal = getattr(acc, 'available_balance', acc.get('available_balance') if isinstance(acc, dict) else None)
                    if isinstance(bal, dict):
                        balances[currency] = Decimal(str(bal.get('value', '0')))
                    else:
                        balances[currency] = Decimal(str(getattr(bal, 'value', '0')))
                return balances
        except Exception:
            return Decimal('0') if asset else {}

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

    def get_supported_pairs(self) -> List[Symbol]:
        try:
            response = self.client.get_products()
            products = getattr(response, 'products', [])
            return [Symbol(p.base_currency, p.quote_currency) for p in products if p.status == 'online' and ('USDT' in p.quote_currency or 'USDC' in p.quote_currency or 'USD' in p.quote_currency)]
        except Exception:
            return [Symbol('BTC', 'USD')]

    def fetch_deposit_address(self, asset: str, network: Optional[str] = None) -> Dict:
        """Fetch deposit address for Coinbase account."""
        try:
            response = self.client.get_accounts()
            accounts = getattr(response, 'accounts', [])
            account_id = next(acc.uuid for acc in accounts if acc.currency == asset.upper())
            addr_res = self.client.create_address(account_id=account_id)
            return {'address': getattr(addr_res, 'address', addr_res.get('address') if isinstance(addr_res, dict) else None)}
        except Exception:
            return {'address': None}

    def get_staking_assets(self) -> List[Dict]:
        """Staking not supported on legacy Wallet API."""
        return []

    def withdraw(self, asset: str, amount: Decimal, address: str, network: str = 'base') -> Dict:
        """Execute withdrawal from Coinbase."""
        try:
            return self.client.create_withdrawal(amount=str(amount), asset=asset, destination=address, network=network)
        except Exception as e:
            return {'success': False, 'error': str(e)}