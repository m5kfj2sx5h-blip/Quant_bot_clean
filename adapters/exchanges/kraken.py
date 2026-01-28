from kraken.spot import SpotClient as KrakenSpot
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

    def get_name(self) -> str:
        return "kraken"

    def get_balance(self, asset: str) -> Decimal:
        balance = self.client.balance()
        return Decimal(balance.get(asset.upper(), '0'))

    def get_all_balances(self) -> Dict[str, Dict[str, Decimal]]:
        """Fetch all balances from Kraken."""
        balance = self.client.balance()
        balances = {}
        for asset, amount in balance.items():
            val = Decimal(str(amount))
            if val > 0:
                # Kraken simple balance doesn't always distinguish free/used easily in one call
                # Assuming simple model for now
                balances[asset.upper()] = {
                    'free': val,
                    'total': val
                }
        return balances

    def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict[str, List[Dict[str, Decimal]]]:
        pair = str(symbol).replace('/', '')
        book = self.client.market_depth(pair=pair, count=limit)
        return {
            'bids': [{'price': Decimal(p[0]), 'amount': Decimal(p[1])} for p in book['bids']],
            'asks': [{'price': Decimal(p[0]), 'amount': Decimal(p[1])} for p in book['asks']]
        }

    def get_ticker_price(self, symbol: Symbol) -> Price:
        pair = str(symbol).replace('/', '')
        ticker = self.client.ticker(pair=pair)
        # The official SDK returns a dict where keys are the pair names if called without list,
        # or it might return it directly. Assuming it follows Kraken API structure.
        # ticker['c'][0] is the last trade closed.
        pair_key = list(ticker.keys())[0] if isinstance(ticker, dict) and 'c' not in ticker else None
        if pair_key:
            return Price(Decimal(ticker[pair_key]['c'][0]))
        return Price(Decimal(ticker['c'][0]))

    def fetch_fees(self) -> Dict[str, Any]:
        """Fetch standardized fee structure for Kraken."""
        trade_volume = self.client.trade_volume()
        return {
            'maker': Decimal(str(trade_volume.get('fees', {}).get('maker', 0.0016))),
            'taker': Decimal(str(trade_volume.get('fees', {}).get('taker', 0.0026))),
            'bnb_discount': False,
            'raw': trade_volume
        }

    def get_market_metadata(self) -> Dict[str, Any]:
        """Fetch all spot trading pairs metadata in one bulk call."""
        pairs = self.client.asset_pairs()
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
        assets_info = self.client.assets()
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
        return self.client.deposit_addresses(asset=asset, method=method)

    def withdraw(self, asset: str, amount: Decimal, address: str, key: str) -> Dict:
        """Execute withdrawal from Kraken."""
        # Kraken uses 'key' (withdrawal template name) or address
        return self.client.withdraw(asset=asset, amount=str(amount), key=key)

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
        pairs = self.client.asset_pairs()
        return [Symbol(key.replace('XXBT', 'BTC').replace('XETH', 'ETH').replace('ZUSD', 'USD').replace('.', '/')) for key in pairs]

    def stake(self, asset: str, amount: Decimal) -> Dict:
        """Stake asset on Kraken"""
        return self.client.privatePostStake({'asset': asset.upper(), 'amount': str(amount)})

    def unstake(self, asset: str, amount: Decimal) -> Dict:
        """Unstake asset from Kraken"""
        return self.client.privatePostUnstake({'asset': asset.upper(), 'amount': str(amount)})

    def get_staking_assets(self) -> List[Dict]:
        """Fetch stakable assets and their APRs."""
        try:
            return self.client.privatePostStakingAssets()
        except:
            return []