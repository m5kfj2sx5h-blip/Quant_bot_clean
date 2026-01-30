from kraken.spot import SpotClient as KrakenSpot, User as KrakenUser, Market as KrakenMarket
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.entities import Symbol
from domain.values import Price, Amount
from dotenv import load_dotenv
import os

load_dotenv('config/.env')

class KrakenAdapter:
    def __init__(self):
        api_key = os.getenv('KRAKEN_KEY')
        api_secret = os.getenv('KRAKEN_SECRET')
        self.client = KrakenSpot(key=api_key, secret=api_secret)
        self.user_client = KrakenUser(key=api_key, secret=api_secret)
        self.market_client = KrakenMarket(key=api_key, secret=api_secret)

    def get_name(self) -> str:
        return "kraken"

    def get_balance(self, asset: Optional[str] = None) -> Any:
        balance = self.user_client.get_account_balance()
        if asset:
            return Decimal(balance.get(asset.upper(), '0'))
        return {k: Decimal(str(v)) for k, v in balance.items()}

    def get_all_balances(self) -> Dict[str, Dict[str, Decimal]]:
        """Fetch all balances from Kraken."""
        balance = self.user_client.get_account_balance()
        balances = {}
        for asset, amount in balance.items():
            val = Decimal(str(amount))
            if val > 0:
                balances[asset.upper()] = {
                    'free': val,
                    'total': val
                }
        return balances

    def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict:
        pair = str(symbol).replace('/', '')
        return self.market_client.get_order_book(pair=pair, count=limit)

    def get_ticker_price(self, symbol: Symbol) -> Price:
        pair = str(symbol).replace('/', '')
        ticker = self.market_client.get_ticker_information(pair=pair)
        # The official SDK returns a dict where keys are the pair names if called without list,
        # or it might return it directly. Assuming it follows Kraken API structure.
        # ticker['c'][0] is the last trade closed.
        pair_key = list(ticker.keys())[0] if isinstance(ticker, dict) and 'c' not in ticker else None
        if pair_key:
            return Price(Decimal(ticker[pair_key]['c'][0]))
        return Price(Decimal(ticker['c'][0]))

    def fetch_fees(self) -> Dict[str, Any]:
        """Fetch standardized fee structure for Kraken with fallback."""
        try:
            trade_volume = self.user_client.get_trade_volume()
            if not trade_volume or not isinstance(trade_volume, dict):
                raise ValueError("Invalid fee response from Kraken")
                
            return {
                'maker': Decimal(str(trade_volume.get('fees', {}).get('maker', 0.0016))),
                'taker': Decimal(str(trade_volume.get('fees', {}).get('taker', 0.0026))),
                'bnb_discount': False,
                'raw': trade_volume
            }
        except Exception as e:
            # Fallback to standard fees if API fails
            return {
                'maker': Decimal('0.0016'),
                'taker': Decimal('0.0026'),
                'bnb_discount': False,
                'raw': {'error': str(e)}
            }

    def get_market_metadata(self) -> Dict[str, Any]:
        """Fetch all spot trading pairs metadata in one bulk call."""
        pairs = self.market_client.get_asset_pairs()
        markets = {}
        for key, s in pairs.items():
            # Kraken keys can be altnames or wsnames
            symbol = s.get('wsname', key).replace('.', '/')
            markets[symbol] = {
                'altname': s['altname'],
                'base': s['base'],
                'quote': s['quote'],
                'precision': {
                    'amount': s['lot_decimals'],
                    'price': s['pair_decimals']
                },
                'min_order': Decimal(str(s.get('ordermin', '0')))
            }
        return markets

    def get_asset_metadata(self) -> Dict[str, Any]:
        """Fetch asset network info dynamically from Kraken."""
        assets_info = self.market_client.get_assets()
        assets = {}
        
        # We only poll a subset of networks to avoid rate limits if needed, 
        # but for discovery we try to map assets.
        for key, a in assets_info.items():
            asset_name = a.get('altname', key)
            assets[asset_name] = {
                'name': asset_name,
                'can_stake': 'staking' in a.get('status', '').lower(),
                'networks': {
                    'KRAKEN': {
                        'withdraw_fee': Decimal('0.0005'), # Default fallback
                        'withdraw_enabled': a.get('status') == 'enabled',
                        'deposit_enabled': a.get('status') == 'enabled'
                    }
                }
            }
            
        # Optional: Try to fetch real withdrawal methods for major arb assets
        # This can be expensive API-wise, so we do it sparingly if registry worker calls it.
        return assets

    def fetch_deposit_address(self, asset: str, method: str = 'Solana') -> Dict:
        """Fetch actual deposit address from Kraken."""
        return self.user_client.get_deposit_addresses(asset=asset, method=method)

    def withdraw(self, asset: str, amount: Decimal, address: str, key: str) -> Dict:
        """Execute withdrawal from Kraken."""
        # Kraken uses 'key' (withdrawal template name) or address
        return self.user_client.withdraw_funds(asset=asset, amount=str(amount), key=key)

    def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict:
        pair = str(symbol).replace('/', '')
        order_type = 'limit' if price else 'market'
        return self.client.create_order(pair=pair, type=side.lower(), ordertype=order_type, volume=str(amount), price=str(price) if price else None)

    def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        try:
            self.client.cancel_order(txid=order_id)
            return True
        except:
            return False

    def get_supported_pairs(self) -> List[Symbol]:
        pairs = self.market_client.get_asset_pairs()
        result = []
        for key, s in pairs.items():
            if s.get('status') == 'online' and ('USDT' in s['quote'] or 'USDC' in s['quote'] or 'USD' in s['quote']):
                result.append(Symbol(s['base'], s['quote']))
        return result if result else [Symbol('BTC', 'USD'), Symbol('ETH', 'USD')]

    def stake(self, asset: str, amount: Decimal) -> Dict:
        """Stake asset on Kraken"""
        # SDK methods are often dynamic or named differently.
        # Kraken SDK Ben Schwertfeger uses privatePostStake style or specific methods.
        try:
            from kraken.spot import Earn
            earn = Earn(key=self.client._key, secret=self.client._secret)
            return earn.allocate_strategy(amount=str(amount), asset=asset.upper())
        except:
            return self.client.privatePostStake({'asset': asset.upper(), 'amount': str(amount)})

    def unstake(self, asset: str, amount: Decimal) -> Dict:
        """Unstake asset from Kraken"""
        try:
            from kraken.spot import Earn
            earn = Earn(key=self.client._key, secret=self.client._secret)
            return earn.deallocate_strategy(amount=str(amount), asset=asset.upper())
        except:
            return self.client.privatePostUnstake({'asset': asset.upper(), 'amount': str(amount)})

    def get_staking_assets(self) -> List[Dict]:
        """Fetch stakable assets and their APRs."""
        try:
            return self.client.privatePostStakingAssets()
        except:
            return []