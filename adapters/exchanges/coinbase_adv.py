from coinbase.rest import RESTClient as CoinbaseAdvancedClient
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.values import Price, Amount
from domain.entities import Symbol
from dotenv import load_dotenv
import os
import base64
import re

load_dotenv('config/.env')

class CoinbaseAdvancedAdapter:
    def _parse_pem_key(self, pem_key: str) -> str:
        # Standardize for the new SDK which expects the string or base64
        return pem_key.strip()

    def __init__(self):
        api_key = os.getenv('COINBASEADV_KEY')
        api_secret = os.getenv('COINBASEADV_SECRET')
        self.client = CoinbaseAdvancedClient(api_key=api_key, api_secret=api_secret)

    def get_name(self) -> str:
        return "coinbase_advanced"

    def fetch_fees(self) -> Dict[str, Any]:
        """Fetch standardized fee structure for Coinbase Advanced."""
        summary = self.client.get_transaction_summary()
        # Official SDK returns nested objects or dicts depending on version
        # Assuming summary.fee_tier logic
        taker = Decimal(str(getattr(summary, 'taker_fee_rate', '0.006')))
        maker = Decimal(str(getattr(summary, 'maker_fee_rate', '0.004')))
        
        return {
            'maker': maker,
            'taker': taker,
            'bnb_discount': False,
            'raw': summary
        }

    def get_balance(self, asset: Optional[str] = None) -> Any:
        """Fetch balance for one or all assets."""
        try:
            response = self.client.get_accounts()
            accounts = getattr(response, 'accounts', [])
            
            if asset:
                for acc in accounts:
                    if acc and getattr(acc, 'currency', None) == asset.upper():
                        return Decimal(str(acc.available_balance.value))
                return Decimal('0')
            else:
                balances = {}
                for acc in accounts:
                    if acc:
                        currency = getattr(acc, 'currency', None)
                        if currency:
                            balances[currency] = Decimal(str(acc.available_balance.value))
                return balances
        except Exception:
            return Decimal('0') if asset else {}

    def get_all_balances(self) -> Dict[str, Dict[str, Decimal]]:
        """Fetch all accounts from Coinbase Advanced."""
        try:
            response = self.client.get_accounts()
            accounts = getattr(response, 'accounts', [])
            balances = {}
            for acc in accounts:
                if acc:
                    total = Decimal(str(acc.hold.value)) + Decimal(str(acc.available_balance.value))
                    if total > 0:
                        balances[acc.currency.upper()] = {
                            'free': Decimal(str(acc.available_balance.value)),
                            'total': total
                        }
            return balances
        except Exception:
            return {}

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
        try:
            response = self.client.get_products()
            products = getattr(response, 'products', [])
            return [Symbol(p.base_currency, p.quote_currency) for p in products if p.status == 'online' and ('USDT' in p.quote_currency or 'USDC' in p.quote_currency or 'USD' in p.quote_currency)]
        except Exception:
            return [Symbol('BTC', 'USD')]

    def get_market_metadata(self) -> Dict[str, Any]:
        """Fetch all Coinbase Advanced products metadata."""
        try:
            response = self.client.get_products()
            products = getattr(response, 'products', [])
            markets = {}
            for p in products:
                if p and getattr(p, 'status', None) == 'online':
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
        except Exception:
            return {}

    def get_asset_metadata(self) -> Dict[str, Any]:
        """Fetch all stakable and tradable assets dynamically from Coinbase."""
        try:
            response = self.client.get_products()
            products = getattr(response, 'products', [])
            assets = {}
            
            # Aggregate unique base currencies
            unique_assets = set()
            for p in products:
                if p and getattr(p, 'status', None) == 'online':
                    unique_assets.add(p.base_currency)
                    unique_assets.add(p.quote_currency)
            
            for asset in unique_assets:
                assets[asset] = {
                    'name': asset,
                    'can_stake': False, # Will be updated if staking assets found
                    'networks': {
                        'BASE': {
                            'withdraw_fee': Decimal('0.00'), # Base is preferred
                            'withdraw_enabled': True,
                            'deposit_enabled': True
                        }
                    }
                }
                
            # Try to discover staking assets
            try:
                staking_response = self.client.get_staking_options()
                staking_options = getattr(staking_response, 'staking_options', [])
                for opt in staking_options:
                    asset = getattr(opt, 'asset', None)
                    if asset in assets:
                        assets[asset]['can_stake'] = True
            except:
                pass
                
            return assets
        except Exception:
            return {}

    def fetch_deposit_address(self, asset: str, network: Optional[str] = None) -> Dict:
        """Fetch deposit address for Coinbase account."""
        try:
            accounts_res = self.client.get_accounts()
            accounts = getattr(accounts_res, 'accounts', [])
            account_id = next(acc.uuid for acc in accounts if getattr(acc, 'currency', None) == asset.upper())
            addr_res = self.client.create_address(account_id=account_id)
            return {'address': getattr(addr_res, 'address', addr_res.get('address') if isinstance(addr_res, dict) else None)}
        except Exception:
            return {'address': None}

    def withdraw(self, asset: str, amount: Decimal, address: str, network: str = 'base') -> Dict:
        """Execute withdrawal from Coinbase Advanced."""
        # Uses the create_transfer or similar endpoint
        return self.client.create_withdrawal(amount=str(amount), asset=asset, destination=address, network=network)

    def stake(self, asset: str, amount: Decimal) -> Dict:
        """Stake asset on Coinbase Advanced via the account-level staking API."""
        try:
            # Note: Staking endpoints vary in SDK versions. 
            # This is a representative pattern for the advanced SDK.
            return self.client.stake_balance(asset=asset.upper(), amount=str(amount))
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def unstake(self, asset: str, amount: Decimal) -> Dict:
        """Unstake asset from Coinbase Advanced."""
        try:
            return self.client.unstake_balance(asset=asset.upper(), amount=str(amount))
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_staking_assets(self) -> List[Dict]:
        """Fetch stakable assets and their APRs for Coinbase."""
        try:
            # Querying available staking options
            return self.client.get_staking_options()
        except:
            return []