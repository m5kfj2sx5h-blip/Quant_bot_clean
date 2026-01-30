from binance.spot import Spot as BinanceSpot
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.entities import Symbol
from domain.values import Price, Amount
from dotenv import load_dotenv
import os

load_dotenv('config/.env')

class BinanceUSAdapter:
    def __init__(self):
        api_key = os.getenv('BINANCEUS_KEY')
        api_secret = os.getenv('BINANCEUS_SECRET')
        # binance-connector expects api_key/api_secret (not key/secret)
        self.client = BinanceSpot(api_key=api_key, api_secret=api_secret, base_url='https://api.binance.us')

    def get_name(self) -> str:
        return "binanceus"

    def get_balance(self, asset: Optional[str] = None) -> Any:
        """Fetch balance for one or all assets."""
        account = self.client.account()
        if asset:
            for b in account['balances']:
                if b['asset'] == asset.upper():
                    return Decimal(b['free'])
            return Decimal('0')
        else:
            return {b['asset']: Decimal(b['free']) for b in account['balances']}

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

    def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict:
        return self.client.depth(str(symbol).replace('/', ''), limit=limit)

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

    def get_order(self, order_id: str, symbol: Symbol) -> Dict:
        """Fetch order status and fill details."""
        try:
            res = self.client.get_order(symbol=str(symbol).replace('/', ''), orderId=order_id)
            # Map status
            status_map = {
                'NEW': 'open',
                'PARTIALLY_FILLED': 'open',
                'FILLED': 'closed',
                'CANCELED': 'canceled',
                'PENDING_CANCEL': 'open',
                'REJECTED': 'canceled',
                'EXPIRED': 'canceled'
            }
            status = status_map.get(res['status'], 'open')
            exec_qty = Decimal(res['executedQty'])
            cumm_quote = Decimal(res['cummulativeQuoteQty'])
            
            avg_price = Decimal('0')
            if exec_qty > 0:
                avg_price = cumm_quote / exec_qty
            
            return {
                'status': status,
                'filled': exec_qty,
                'remaining': Decimal(res['origQty']) - exec_qty,
                'avg_price': avg_price,
                'fee': Decimal('0') # Binance doesn't return trade fee in order status easily
            }
        except Exception as e:
            return {'status': 'unknown', 'error': str(e), 'filled': Decimal('0'), 'avg_price': Decimal('0')}

    def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        try:
            self.client.cancel_order(str(symbol).replace('/', ''), orderId=order_id)
            return True
        except:
            return False

    def get_supported_pairs(self) -> List[Symbol]:
        exchange_info = self.client.exchange_info()
        return [Symbol(s['baseAsset'], s['quoteAsset']) for s in exchange_info['symbols'] if s['status'] == 'TRADING' and ('USDT' in s['quoteAsset'] or 'USDC' in s['quoteAsset'] or 'USD' in s['quoteAsset'])]

    def stake(self, asset: str, amount: Decimal) -> Dict:
        """Stake asset on Binance.US with fallback."""
        try:
            return self.client.staking_subscribe(product='STAKING', asset=asset.upper(), amount=float(amount))
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def unstake(self, asset: str, amount: Decimal) -> Dict:
        """Unstake asset on Binance.US with fallback."""
        try:
            return self.client.staking_redeem(product='STAKING', asset=asset.upper(), amount=float(amount))
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_staking_assets(self) -> List[Dict]:
        """Fetch stakable assets and their APRs with fallback."""
        try:
            return self.client.staking_product_list(product='STAKING')
        except Exception:
            return []
