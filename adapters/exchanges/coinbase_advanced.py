import ccxt.async_support as ccxt
import base64
import re
from ecdsa import SigningKey
from ecdsa.util import sigencode_der
from decimal import Decimal
from typing import Dict, List, Any, Optional

from exchanges.base import ExchangeAdapter
from domain.values import Price, Amount, Symbol

class CoinbaseAdvancedAdapter(ExchangeAdapter):
    @staticmethod
    def _parse_pem_key(pem_key: str) -> bytes:
        try:
            pem_key = pem_key.strip()
            if '-----BEGIN PRIVATE KEY-----' in pem_key:
                b64_key = re.search(r'-----BEGIN PRIVATE KEY-----(.*?)-----END PRIVATE KEY-----', pem_key, re.DOTALL)
                if b64_key:
                    key_data = b64_key.group(1).replace('\n', '')
                else:
                    raise ValueError("Invalid PEM format")
            else:
                key_data = pem_key.replace('\n', '')
            key_bytes = base64.b64decode(key_data)
            try:
                key = SigningKey.from_der(key_bytes)
                return key.to_der()
            except:
                return key_bytes
        except Exception as e:
            return b''

    def __init__(self, config: Dict[str, Any]):
        parsed_secret = self._parse_pem_key(config['api_secret'])
        self.client = ccxt.coinbaseadvanced({
            'apiKey': config['api_key'],
            'secret': base64.b64encode(parsed_secret).decode() if parsed_secret else config['api_secret'],
            'enableRateLimit': True
        })

    def get_name(self) -> str:
        return "coinbase_advanced"

    async def get_balance(self, asset: str) -> Decimal:
        balance = await self.client.fetch_balance()
        return Decimal(balance.get(asset.upper(), {}).get('free', '0'))

    async def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict[str, List[Dict[str, Decimal]]]:
        book = await self.client.fetch_order_book(str(symbol).replace('/', '-'), limit)
        return {
            'bids': [{ 'price': Decimal(p[0]), 'amount': Decimal(p[1]) } for p in book['bids']],
            'asks': [{ 'price': Decimal(p[0]), 'amount': Decimal(p[1]) } for p in book['asks']]
        }

    async def get_ticker_price(self, symbol: Symbol) -> Price:
        ticker = await self.client.fetch_ticker(str(symbol).replace('/', '-'))
        return Price(Decimal(ticker['last']))

    async def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict:
        params = {}
        return await self.client.create_order(
            str(symbol).replace('/', '-'), 'limit' if price else 'market', side, float(amount), float(price) if price else None, params
        )

    async def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        try:
            await self.client.cancel_order(order_id, str(symbol).replace('/', '-'))
            return True
        except:
            return False

    def get_supported_pairs(self) -> List[Symbol]:
        markets = self.client.load_markets()
        return [Symbol(pair.replace('-', '/')) for pair in markets if 'USDT' in pair or 'USDC' in pair or 'USD' in pair]  # Prioritizes USDT/USDC