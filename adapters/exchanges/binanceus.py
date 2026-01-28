from binance.spot import Spot as BinanceSpot
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.entities import Symbol
from domain.values import Price, Amount
from dotenv import load_dotenv
import os

load_dotenv()

class BinanceUSAdapter:
    def __init__(self):
        api_key = os.getenv('BINANCEUS_API_KEY')
        api_secret = os.getenv('BINANCEUS_API_SECRET')
        self.client = BinanceSpot(key=api_key, secret=api_secret, base_url='https://api.binance.us')

    def get_name(self) -> str:
        return "binanceus"

    def get_balance(self, asset: str) -> Decimal:
        balance = self.client.account()['balances']
        for b in balance:
            if b['asset'] == asset.upper():
                return Decimal(b['free'])
        return Decimal('0')

    def get_all_balances(self) -> Dict[str, Dict[str, Decimal]]:
        """Fetch all balances in one call."""
        account = self.client.account()
        balances = {}
        for b in account['balances']:
            total = Decimal(b['free']) + Decimal(b['locked'])
            if total > 0:
                balances[b['asset']] = {
                    'free': Decimal(b['free']),
                    'total': total
                }
        return balances

    def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict[str, List[Dict[str, Decimal]]]:
        book = self.client.depth(str(symbol).replace('/', ''), limit=limit)
        return {
            'bids': [{'price': Decimal(p[0]), 'amount': Decimal(p[1])} for p in book['bids']],
            'asks': [{'price': Decimal(p[0]), 'amount': Decimal(p[1])} for p in book['asks']]
        }

    def get_ticker_price(self, symbol: Symbol) -> Price:
        ticker = self.client.ticker_price(str(symbol).replace('/', ''))
        return Price(Decimal(ticker['price']))

    def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict:
        params = {
            'symbol': str(symbol).replace('/', ''),
            'side': side.upper(),
            'type': 'LIMIT' if price else 'MARKET',
            'quantity': str(amount)
        }
        if price:
            params['price'] = str(price)
            params['timeInForce'] = 'GTC'
        return self.client.new_order(**params)

    def fetch_fees(self) -> Dict[str, Any]:
        """Fetch standardized fee structure."""
        account_info = self.client.account()
        return {
            'maker': Decimal(str(account_info.get('makerCommission', 0.001))),
            'taker': Decimal(str(account_info.get('takerCommission', 0.001))),
            'bnb_discount': account_info.get('canUseBnbForFees', False),
            'raw': account_info
        }

    def get_market_metadata(self) -> Dict[str, Any]:
        """Fetch all spot trading pairs metadata in one bulk call."""
        exchange_info = self.client.exchange_info()
        markets = {}
        for s in exchange_info['symbols']:
            if s['status'] == 'TRADING':
                symbol = f"{s['baseAsset']}/{s['quoteAsset']}"
                markets[symbol] = {
                    'base': s['baseAsset'],
                    'quote': s['quoteAsset'],
                    'precision': {
                        'amount': s['baseAssetPrecision'],
                        'price': s['quotePrecision']
                    },
                    'filters': s['filters']
                }
        return markets

    def get_asset_metadata(self) -> Dict[str, Any]:
        """Fetch all asset withdrawal fees and network statuses in one bulk call."""
        coins = self.client.coin_info() # SAPI call for all coins
        assets = {}
        for c in coins:
            asset = c['coin']
            networks = {}
            for net in c['networkList']:
                networks[net['network']] = {
                    'withdraw_fee': Decimal(str(net['withdrawFee'])),
                    'withdraw_enabled': net['withdrawEnable'],
                    'deposit_enabled': net['depositEnable'],
                    'min_withdraw': Decimal(str(net['withdrawMin']))
                }
            assets[asset] = {
                'name': c['name'],
                'can_stake': False, # Binance.US staking is separate
                'networks': networks
            }
        return assets

    def fetch_deposit_address(self, asset: str, network: Optional[str] = None) -> Dict:
        """Fetch actual deposit address from API."""
        params = {'coin': asset.upper()}
        if network:
            params['network'] = network
        return self.client.deposit_address(**params)

    def withdraw(self, asset: str, amount: Decimal, address: str, network: str, params: Dict = None) -> Dict:
        """Execute withdrawal using specific network."""
        return self.client.withdraw(
            coin=asset.upper(),
            amount=float(amount),
            address=address,
            network=network,
            **(params or {})
        )

    def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        try:
            self.client.cancel_order(str(symbol).replace('/', ''), orderId=order_id)
            return True
        except:
            return False

    def get_supported_pairs(self) -> List[Symbol]:
        exchange_info = self.client.exchange_info()
        return [Symbol(s['baseAsset'] + '/' + s['quoteAsset']) for s in exchange_info['symbols'] if s['status'] == 'TRADING' and ('USDT' in s['quoteAsset'] or 'USDC' in s['quoteAsset'] or 'USD' in s['quoteAsset'])]

    def stake(self, asset: str, amount: Decimal) -> Dict:
        """Stake asset on Binance.US"""
        return self.client.staking_subscribe(product='STAKING', asset=asset.upper(), amount=float(amount))

    def unstake(self, asset: str, amount: Decimal) -> Dict:
        """Unstake asset on Binance.US"""
        return self.client.staking_redeem(product='STAKING', asset=asset.upper(), amount=float(amount))

    def get_staking_assets(self) -> List[Dict]:
        """Fetch stakable assets and their APRs."""
        return self.client.staking_product_list(product='STAKING')