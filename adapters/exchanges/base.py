from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
from decimal import Decimal  # Preserve Decimal usage from your strategy
from domain.values import Symbol, Amount, Price  # Assuming domain exists; adjust import if needed
import logging

class ExchangeAdapter(ABC):
    """Abstract base class for exchange adapters (preserves your ExchangeWrapper ABC)"""

    def __init__(self, exchange_name: str, config: Dict[str, Any]):
        self.name = exchange_name
        self.config = config
        self.exchange = None
        self.connected = False
        self.logger = logging.getLogger(f"{__name__}.{exchange_name}")

        # Preserve: Add WebSocket support flag for latency mode detection
        self.use_websocket = True

    def connect(self) -> bool:
        """Connect to the exchange (exact copy from your ExchangeWrapper.connect)"""
        try:
            exchange_class = getattr(ccxt, self.name.lower())
            exchange_config = {
                'apiKey': self.config.get('api_key', ''),
                'secret': self.config.get('api_secret', ''),
                'enableRateLimit': True,
                'timeout': 30000,
            }

            # Preserve: Add exchange-specific options
            if self.name.lower() == 'binanceus':
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
    def create_order(self, symbol: Symbol, order_type: str, side: str,
                     amount: Amount, price: Optional[Price] = None) -> Dict[str, Any]:
        """Create an order on the exchange"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: Symbol) -> bool:
        """Cancel an order on the exchange"""
        pass

    def get_balance(self) -> Dict[str, float]:
        """Get account balance (exact copy from your ExchangeWrapper.get_balance)"""
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
            self.logger.error(f"❌ Error fetching balance from {self.name}: {e}")
            return {}

    def get_ticker(self, symbol: Symbol) -> Optional[Dict[str, Any]]:
        """Get ticker for a symbol (exact copy from your ExchangeWrapper.get_ticker)"""
        try:
            if not self.connected or not self.exchange:
                return None

            return self.exchange.fetch_ticker(str(symbol))

        except Exception as e:
            self.logger.error(f"❌ Error fetching ticker from {self.name}: {e}")
            return None

    def get_order_book(self, symbol: Symbol, limit: int = 10) -> Optional[Dict[str, Any]]:
        """Get order book for a symbol (exact copy from your ExchangeWrapper.get_order_book)"""
        try:
            if not self.connected or not self.exchange:
                return None

            return self.exchange.fetch_order_book(str(symbol), limit)

        except Exception as e:
            self.logger.error(f"❌ Error fetching order book from {self.name}: {e}")
            return None