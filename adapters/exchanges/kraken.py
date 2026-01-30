from kraken.spot import SpotClient as KrakenSpot, User as KrakenUser, Market as KrakenMarket
from decimal import Decimal
from typing import Dict, List, Any, Optional
from domain.entities import Symbol
from domain.values import Price, Amount
from dotenv import load_dotenv
import os

load_dotenv('config/.env')

class KrakenAdapter:
    def __init__(self, config: Dict = None):
        self.config = config or {}
        api_key = os.getenv('KRAKEN_KEY')
        api_secret = os.getenv('KRAKEN_SECRET')
        self.client = KrakenSpot(key=api_key, secret=api_secret)
        self.user_client = KrakenUser(key=api_key, secret=api_secret)
        self.market_client = KrakenMarket(key=api_key, secret=api_secret)

    def get_name(self) -> str:
        return "kraken"

    def get_balance(self, asset: Optional[str] = None) -> Any:
        # Kraken uses non-standard symbols - normalize them
        SYMBOL_MAP = {
            'XXBT': 'BTC', 'XBT': 'BTC',
            'XETH': 'ETH',
            'XXRP': 'XRP',
            'XLTC': 'LTC',
            'XXDG': 'DOGE', 'XDG': 'DOGE',
            'ZUSD': 'USD',
            'ZEUR': 'EUR',
            'ZGBP': 'GBP',
        }
        REVERSE_MAP = {v: k for k, v in SYMBOL_MAP.items()}  # BTC -> XXBT
        
        balance = self.user_client.get_account_balance()
        
        if asset:
            # Try both normalized and Kraken format
            kraken_asset = REVERSE_MAP.get(asset.upper(), asset.upper())
            return Decimal(balance.get(asset.upper(), balance.get(kraken_asset, '0')))
        
        # Return normalized keys
        result = {}
        for k, v in balance.items():
            normalized = SYMBOL_MAP.get(k.upper(), k.upper())
            result[normalized] = Decimal(str(v))
        return result

    def get_all_balances(self) -> Dict[str, Dict[str, Decimal]]:
        """Fetch all balances from Kraken."""
        # Kraken uses non-standard symbols - normalize them
        SYMBOL_MAP = {
            'XXBT': 'BTC', 'XBT': 'BTC',
            'XETH': 'ETH',
            'XXRP': 'XRP',
            'XLTC': 'LTC',
            'XXDG': 'DOGE', 'XDG': 'DOGE',
            'ZUSD': 'USD',
            'ZEUR': 'EUR',
            'ZGBP': 'GBP',
        }
        
        balance = self.user_client.get_account_balance()
        balances = {}
        for asset, amount in balance.items():
            val = Decimal(str(amount))
            if val > 0:
                # Normalize the asset name
                normalized = SYMBOL_MAP.get(asset.upper(), asset.upper())
                balances[normalized] = {
                    'free': val,
                    'total': val
                }
        return balances

    def _to_kraken_symbol(self, symbol: str) -> str:
        """Convert normalized symbol (BTC/USDT) to Kraken format (XBTUSDT)."""
        # Kraken uses non-standard symbols
        REVERSE_MAP = {
            'BTC': 'XBT',  # Kraken uses XBT not BTC
            'DOGE': 'XDG',
        }
        
        # Parse the symbol
        if '/' in symbol:
            base, quote = symbol.split('/')
        else:
            base, quote = symbol[:3], symbol[3:] if len(symbol) > 3 else ''
        
        # Convert to Kraken format
        kraken_base = REVERSE_MAP.get(base.upper(), base.upper())
        kraken_quote = quote.upper()
        
        return f"{kraken_base}{kraken_quote}"

    def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict:
        pair = self._to_kraken_symbol(str(symbol))
        response = self.market_client.get_order_book(pair=pair, count=limit)
        
        # Kraken returns nested dict: {'XBTUSDT': {'bids': [[price, qty, ts], ...], 'asks': [...]}}
        # Normalize to standard format: {'bids': [[price, qty], ...], 'asks': [[price, qty], ...]}
        if isinstance(response, dict) and len(response) == 1:
            # Unwrap the nested response
            inner = list(response.values())[0]
            if isinstance(inner, dict) and 'bids' in inner:
                # Strip timestamp from triplets
                bids = [[b[0], b[1]] for b in inner.get('bids', [])]
                asks = [[a[0], a[1]] for a in inner.get('asks', [])]
                return {'bids': bids, 'asks': asks}
        
        # Fallback if already in expected format
        return response if isinstance(response, dict) and 'bids' in response else {'bids': [], 'asks': []}

    def get_ticker_price(self, symbol: Symbol) -> Price:
        pair = self._to_kraken_symbol(str(symbol))
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
        assets = {}
        # Fetch generic info
        assets_info = self.market_client.get_assets()
        
        # We focus on STABLES for Transfers (USDT, USDC) to avoid rate limits on 100+ coins
        target_assets = ['USDT', 'USDC']
        
        for key, a in assets_info.items():
            asset_name = a.get('altname', key)
            # Default to Unknown/None if not fetched
            withdraw_fee = None 
            
            if asset_name in target_assets:
                try:
                    # Kraken requires a 'key' (address name) to check fee. 
                    # If we don't have one, we can't check specific network fee easily without specific endpoint.
                    # We try 'get_withdraw_info' if we can guess a key or if it allows null key?
                    # Fallback: Use public asset info if available or leave None.
                    # The public AssetPairs doesn't show withdraw fees.
                    # We'll leave it None so functionality triggers "Live Fetch" in TransferManager if needed.
                    pass
                except:
                    pass

            assets[asset_name] = {
                'name': asset_name,
                'can_stake': 'staking' in a.get('status', '').lower(),
                'networks': {
                    'KRAKEN': { 
                        'withdraw_fee': withdraw_fee, 
                        'withdraw_enabled': a.get('status') == 'enabled',
                        'deposit_enabled': a.get('status') == 'enabled'
                    }
                }
            }
        return assets

    def fetch_deposit_address(self, asset: str, method: str = 'Solana') -> Dict:
        """Fetch actual deposit address from Kraken."""
        return self.user_client.get_deposit_addresses(asset=asset, method=method)

    def withdraw(self, asset: str, amount: Decimal, address: str, key: str) -> Dict:
        """Execute withdrawal from Kraken."""
        # --- PAPER MODE CHECK ---
        is_paper = str(self.config.get('paper_mode', 'false')).lower() == 'true'
        if is_paper:
            return {'refid': f'paper_withdraw_{asset}_{amount}'}
        # ------------------------
        
        # Kraken uses 'key' (withdrawal template name) or address
        try:
             # Try standard withdrawal
             return self.user_client.withdraw_funds(asset=asset, amount=str(amount), key=key)
        except AttributeError:
             # Fallback if method named differently in this version
             # print("Kraken SDK version mismatch, attempting raw request")
             return self.client.privatePostWithdraw({'asset': asset, 'key': key, 'amount': str(amount)})
    
    def get_order(self, order_id: str, symbol: Symbol) -> Dict:
        """Fetch order status from Kraken."""
        try:
            # Kraken SDK get_orders_info expects comma-separated txids
            res = self.user_client.get_orders_info(txid=order_id)
            if not res or 'result' not in res or order_id not in res['result']:
                return {'status': 'unknown', 'filled': Decimal('0'), 'avg_price': Decimal('0'), 'fee': Decimal('0')}
            
            info = res['result'][order_id]
            k_status = info['status'] # pending, open, closed, canceled, expired
            status_map = {
                'pending': 'open',
                'open': 'open', 
                'closed': 'closed', 
                'canceled': 'canceled', 
                'expired': 'canceled'
            }
            status = status_map.get(k_status, 'open')
            
            filled = Decimal(str(info['vol_exec']))
            cost = Decimal(str(info['cost']))
            fee = Decimal(str(info['fee']))
            
            avg_price = Decimal('0')
            if filled > 0:
                avg_price = cost / filled
                
            return {
                'status': status,
                'filled': filled,
                'remaining': Decimal(str(info['vol'])) - filled,
                'avg_price': avg_price,
                'fee': fee
            }
        except Exception as e:
            return {'status': 'unknown', 'error': str(e), 'filled': Decimal('0'), 'avg_price': Decimal('0')}

    def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict:
        pair = self._to_kraken_symbol(str(symbol))
        order_type = 'limit' if price else 'market'
        return self.client.create_order(pair=pair, type=side.lower(), ordertype=order_type, volume=str(amount), price=str(price) if price else None)

    def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        try:
            self.client.cancel_order(txid=order_id)
            return True
        except:
            return False

    def get_supported_pairs(self) -> List[Symbol]:
        # Kraken uses non-standard symbols - normalize them
        SYMBOL_MAP = {
            'XXBT': 'BTC', 'XBT': 'BTC',
            'XETH': 'ETH',
            'XXRP': 'XRP',
            'XLTC': 'LTC',
            'XXDG': 'DOGE', 'XDG': 'DOGE',
            'ZUSD': 'USD',
            'ZEUR': 'EUR',
            'ZGBP': 'GBP',
        }
        
        def normalize(sym):
            return SYMBOL_MAP.get(sym, sym)
        
        pairs = self.market_client.get_asset_pairs()
        result = []
        for key, s in pairs.items():
            if s.get('status') == 'online' and ('USDT' in s['quote'] or 'USDC' in s['quote'] or 'USD' in s['quote']):
                base = normalize(s['base'])
                quote = normalize(s['quote'])
                result.append(Symbol(base, quote))
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