# File: wrappers.py
# Create this file in your QUANT_bot directory

"""
Exchange Wrappers Module
Provides unified interfaces for different cryptocurrency exchanges
"""
import ccxt
import logger
import logging
import base64
import re
from abc import ABC, abstractmethod
from domain.values import Symbol, Amount, Price  #<<---- NEEDS FIXING!!
from typing import Dict, Optional, Any
from abc import ABC, abstractmethod
from ecdsa import SigningKey, VerifyingKey
from ecdsa.util import sigencode_der


logger = logging.getLogger(__name__)


class ExchangeWrapper(ABC):
    """Abstract base class for exchange wrappers"""
    
    def __init__(self, exchange_name: str, config: Dict[str, Any]):
        self.name = exchange_name
        self.config = config
        self.exchange = None
        self.connected = False
        self.logger = logging.getLogger(f"{__name__}.{exchange_name}")
        
        # FIX: Add WebSocket support flag for latency mode detection
        self.use_websocket = True
        
    def connect(self) -> bool:
        """Connect to the exchange"""
        try:
            exchange_class = getattr(ccxt, self.name.lower())
            exchange_config = {
                'apiKey': self.config.get('api_key', ''),
                'secret': self.config.get('api_secret', ''),
                'enableRateLimit': True,
                'timeout': 30000,
            }
            
            # Add exchange-specific options
            if self.name.lower() == 'binance':
                exchange_config['options'] = {'defaultType': 'spot'}
            elif self.name.lower() == 'kraken':
                exchange_config['options'] = {'rateLimit': 2000}
            
            self.exchange = exchange_class(exchange_config)
            self.exchange.load_markets()
            self.connected = True
            
            self.logger.info(f"✅ Connected to {self.name}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to connect to {self.name}: {e}")
            return False
    
    @abstractmethod
    def create_order(self, symbol: str, order_type: str, side: str, 
                    amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """Create an order on the exchange"""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order on the exchange"""
        pass
    
    def get_balance(self) -> Dict[str, float]:
        """Get account balance"""
        try:
            if not self.connected or not self.exchange:
                return {}
            
            balance = self.exchange.fetch_balance()
            return {
                'total': balance.get('total', {}),
                'free': balance.get('free', {}),
                'used': balance.get('used', {})
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching balance from {self.name}: {e}")
            return {}
    
    def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get ticker for a symbol"""
        try:
            if not self.connected or not self.exchange:
                return None
            
            return self.exchange.fetch_ticker(symbol)
            
        except Exception as e:
            self.logger.error(f"Error fetching ticker from {self.name}: {e}")
            return None
    
    def get_order_book(self, symbol: str, limit: int = 10) -> Optional[Dict[str, Any]]:
        """Get order book for a symbol"""
        try:
            if not self.connected or not self.exchange:
                return None
            
            return self.exchange.fetch_order_book(symbol, limit)
            
        except Exception as e:
            self.logger.error(f"Error fetching order book from {self.name}: {e}")
            return None


class KrakenWrapper(ExchangeWrapper):
    """Kraken exchange wrapper"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__('kraken', config)
    
    def create_order(self, symbol: str, order_type: str, side: str, 
                    amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """Create an order on Kraken"""
        try:
            if not self.connected or not self.exchange:
                raise Exception("Not connected to Kraken")
            
            order_params = {}
            if order_type == 'limit':
                if price is None:
                    raise Exception("Price required for limit order")
                order_params['price'] = self.exchange.price_to_precision(symbol, price)
            
            amount_str = self.exchange.amount_to_precision(symbol, amount)
            
            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount_str,
                price=price,
                params=order_params
            )
            
            self.logger.info(f"✅ Order created on Kraken: {order['id']}")
            return order
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create order on Kraken: {e}")
            raise
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order on Kraken"""
        try:
            if not self.connected or not self.exchange:
                return False
            
            self.exchange.cancel_order(order_id, symbol)
            self.logger.info(f"✅ Order {order_id} cancelled on Kraken")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to cancel order {order_id} on Kraken: {e}")
            return False


class BinanceUSWrapper(ExchangeWrapper):
    """BinanceUS exchange wrapper"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__('binance', config)
    
    def create_order(self, symbol: str, order_type: str, side: str, 
                    amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """Create an order on BinanceUS"""
        try:
            if not self.connected or not self.exchange:
                raise Exception("Not connected to BinanceUS")
            
            # Binance requires specific handling
            order_params = {}
            if order_type == 'limit':
                if price is None:
                    raise Exception("Price required for limit order")
                order_params['timeInForce'] = 'GTC'  # Good Till Cancelled
            
            amount_str = self.exchange.amount_to_precision(symbol, amount)
            
            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount_str,
                price=price,
                params=order_params
            )
            
            self.logger.info(f"✅ Order created on BinanceUS: {order['id']}")
            return order
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create order on BinanceUS: {e}")
            raise
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order on BinanceUS"""
        try:
            if not self.connected or not self.exchange:
                return False
            
            self.exchange.cancel_order(order_id, symbol)
            self.logger.info(f"✅ Order {order_id} cancelled on BinanceUS")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to cancel order {order_id} on BinanceUS: {e}")
            return False


class CoinbaseAdvancedWrapper(ExchangeWrapper):
    @staticmethod
    def _parse_pem_key(pem_key: str) -> bytes:
        """
        FIX for IndexError: Handles malformed PEM keys that ccxt chokes on
        This is the exact fix from QUANT_bot 2.1
        """
        try:
            # Remove headers/footers and whitespace
            pem_key = pem_key.strip()
            if '-----BEGIN PRIVATE KEY-----' in pem_key:
                # Already in PEM format, extract base64
                b64_key = re.search(
                    r'-----BEGIN PRIVATE KEY-----(.*?)-----END PRIVATE KEY-----',
                    pem_key,
                    re.DOTALL
                )
                if b64_key:
                    key_data = b64_key.group(1).replace('\n', '')
                else:
                    raise ValueError("Invalid PEM format")
            else:
                # Assume it's base64 encoded already
                key_data = pem_key.replace('\n', '')

            # Decode base64
            key_bytes = base64.b64decode(key_data)

            # Verify it's a valid ECDSA key
            try:
                # Try to load as DER key first
                key = SigningKey.from_der(key_bytes)
                return key.to_der()
            except:
                # If that fails, it's probably already a valid key
                return key_bytes

        except Exception as e:
            logger.error(f"Key parsing failed: {e}")
            # Return empty bytes to trigger proper error handling
            return b''

    def __init__(self, api_key: str, api_secret: str, sandbox: bool = False):
        # Parse the key properly before passing to ccxt
        parsed_secret = self._parse_pem_key(api_secret)

        self.exchange = ccxt.coinbaseadvanced({
            'apiKey': api_key,
            'secret': base64.b64encode(parsed_secret).decode() if parsed_secret else api_secret,
            'enableRateLimit': True,
            'options': {
                'sandboxMode': sandbox,
            }
        })

        # Test authentication on init
        try:
            self.exchange.fetch_balance()
            logger.info("coinbaseadvanced authentication successful")
        except IndexError as e:
            logger.error(f"coinbaseadvanced IndexError on init: {e}")
            raise RuntimeError("coinbaseadvanced PEM key parsing failed - check your API secret format")
        except Exception as e:
            logger.warning(f"coinbaseadvanced test call failed (may be sandbox): {e}")


class CoinbaseWrapper(ExchangeWrapper):
    """Coinbase exchange wrapper"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__('coinbase', config)
    
    def create_order(self, symbol: str, order_type: str, side: str, 
                    amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """Create an order on Coinbase"""
        try:
            if not self.connected or not self.exchange:
                raise Exception("Not connected to Coinbase")
            
            # Coinbase specific handling
            order_params = {}
            
            amount_str = self.exchange.amount_to_precision(symbol, amount)
            
            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount_str,
                price=price,
                params=order_params
            )
            
            self.logger.info(f"✅ Order created on Coinbase: {order['id']}")
            return order
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create order on Coinbase: {e}")
            raise
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order on Coinbase"""
        try:
            if not self.connected or not self.exchange:
                return False
            
            self.exchange.cancel_order(order_id, symbol)
            self.logger.info(f"✅ Order {order_id} cancelled on Coinbase")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to cancel order {order_id} on Coinbase: {e}")
            return False


class ExchangeWrapperFactory:
    """Factory for creating exchange wrappers"""
    
    @staticmethod
    def create_wrapper(exchange_name: str, config: Dict[str, Any]) -> Optional[ExchangeWrapper]:
        """Create an exchange wrapper instance"""
        exchange_name = exchange_name.lower()
        
        if exchange_name == 'kraken':
            return KrakenWrapper(config)
        elif exchange_name == 'coinbaseadvanced':
            return CoinbaseAdvancedWrapper(config)
        elif exchange_name == 'coinbase':
            return CoinbaseWrapper(config)
        elif exchange_name == 'binanceus':
            return BinanceUSWrapper(config)  # Binance.US uses same wrapper
        else:
            logger.error(f"Unsupported exchange: {exchange_name}")
            return None
    
    @staticmethod
    def initialize_all_wrappers(exchange_configs: Dict[str, Dict[str, Any]]) -> Dict[str, ExchangeWrapper]:
        """Initialize all exchange wrappers from config"""
        wrappers = {}
        
        for exchange_name, config in exchange_configs.items():
            if config.get('enabled', False):
                wrapper = ExchangeWrapperFactory.create_wrapper(exchange_name, config)
                if wrapper and wrapper.connect():
                    wrappers[exchange_name] = wrapper
        
        return wrappers
