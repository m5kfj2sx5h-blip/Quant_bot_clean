from coinbase.advanced.client import AdvancedTradeClient as CoinbaseAdvancedClient
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.entities import Symbol
from domain.values import Price, Amount
from dotenv import load_dotenv
import os
import base64
import re

load_dotenv()

class CoinbaseAdvancedAdapter:
    def _parse_pem_key(pem_key: str) -> bytes:
        pem_key = pem_key.strip()
        if '-----BEGIN PRIVATE KEY-----' in pem_key:
            b64_key = re.search(r'-----BEGIN PRIVATE KEY-----(.*?)-----END PRIVATE KEY-----', pem_key, re.DOTALL)
            key_data = b64_key.group(1).replace('\n', '') if b64_key else ''
        elif '-----BEGIN EC PRIVATE KEY-----' in pem_key:
            b64_key = re.search(r'-----BEGIN EC PRIVATE KEY-----(.*?)-----END EC PRIVATE KEY-----', pem_key, re.DOTALL)
            key_data = b64_key.group(1).replace('\n', '').replace(' ', '') if b64_key else ''
        else:
            key_data = pem_key.replace('\n', '')
        return base64.b64decode(key_data)

    def __init__(self):
        api_key = os.getenv('COINBASE_ADVANCED_API_KEY')
        api_secret = os.getenv('COINBASE_ADVANCED_API_SECRET')
        parsed_secret = self._parse_pem_key(api_secret)
        self.client = CoinbaseAdvancedClient(api_key=api_key, api_secret=base64.b64encode(parsed_secret).decode())

    def get_name(self) -> str:
        return "coinbase_advanced"

    def get_balance(self, asset: str) -> Decimal:
        accounts = self.client.get_accounts()
        for acc in accounts:
            if acc.currency == asset.upper():
                return Decimal(acc.available_balance.value)
        return Decimal('0')

    def get_all_balances(self) -> Dict[str, Dict[str, Decimal]]:
        """Fetch all accounts from Coinbase Advanced."""
        accounts = self.client.get_accounts()
        balances = {}
        for acc in accounts:
            total = Decimal(acc.hold.value) + Decimal(acc.available_balance.value)
            if total > 0:
                balances[acc.currency.upper()] = {
                    'free': Decimal(acc.available_balance.value),
                    'total': total
                }
        return balances

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
            self.client.cancel_orders([order_id])
            return True
        except:
            return False

    def get_supported_pairs(self) -> List[Symbol]:
        products = self.client.get_products()
        return [Symbol(p.base_currency + '/' + p.quote_currency) for p in products if p.status == 'online' and ('USDT' in p.quote_currency or 'USDC' in p.quote_currency or 'USD' in p.quote_currency)]

    def get_market_metadata(self) -> Dict[str, Any]:
        """Fetch all Coinbase Advanced products metadata."""
        products = self.client.get_products()
        markets = {}
        for p in products:
            if p.status == 'online':
                symbol = f"{p.base_currency}/{p.quote_currency}"
                markets[symbol] = {
                    'base': p.base_currency,
                    'quote': p.quote_currency,
                    'precision': {
                        'amount': p.base_increment,
                        'price': p.quote_increment
                    }
                }
        return markets

    def get_asset_metadata(self) -> Dict[str, Any]:
        """Fetch Coinbase asset info. Fees are often account-tier based."""
        # Coinbase Advanced uses a unified fee structure for most pairs
        fees = self.client.get_transaction_summary()
        assets = {}
        # We'll populate this with common assets; CB doesn't have a bulk 'coin_info' like Binance
        for asset in ['BTC', 'ETH', 'USDT', 'USDC', 'SOL']:
            assets[asset] = {
                'name': asset,
                'can_stake': False,
                'networks': {
                    'BASE': {
                        'withdraw_fee': Decimal('0.00'), # Base network is often near-zero
                        'withdraw_enabled': True,
                        'deposit_enabled': True
                    }
                }
            }
        return assets

    def fetch_deposit_address(self, asset: str) -> Dict:
        """Fetch deposit address for Coinbase account."""
        accounts = self.client.get_accounts()
        account_id = next(acc.uuid for acc in accounts if acc.currency == asset.upper())
        return self.client.create_address(account_id=account_id)

    def withdraw(self, asset: str, amount: Decimal, address: str, network: str = 'base') -> Dict:
        """Execute withdrawal from Coinbase Advanced."""
        # Uses the create_transfer or similar endpoint
        return self.client.create_withdrawal(amount=str(amount), asset=asset, destination=address, network=network)

    def stake(self, asset: str, amount: Decimal) -> Dict:
        """Stake asset on Coinbase Advanced"""
        # Note: Official SDK support for staking varies. 
        # Implementing as a unified port even if logic is limited.
        return {}

    def unstake(self, asset: str, amount: Decimal) -> Dict:
        """Unstake asset from Coinbase Advanced"""
        return {}

    def get_staking_assets(self) -> List[Dict]:
        """Fetch stakable assets and their APRs."""
        return []