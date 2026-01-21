from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional, Any

from domain.values import Price, Amount, Symbol

class ExchangeAdapter(ABC):
    @abstractmethod
    def get_name(self) -> str: pass

    @abstractmethod
    async def get_balance(self, asset: str) -> Decimal: pass

    @abstractmethod
    async def get_order_book(self, symbol: Symbol, limit: int = 5) -> Dict: pass

    @abstractmethod
    async def get_ticker_price(self, symbol: Symbol) -> Price: pass

    @abstractmethod
    async def place_order(self, symbol: Symbol, side: str, amount: Amount, price: Optional[Price] = None) -> Dict: pass

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: Symbol) -> bool: pass

    @abstractmethod
    def get_supported_pairs(self) -> List[Symbol]: pass