"""
Core domain entities - pure business logic, no infrastructure
"""
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal
from typing import Dict, List, Optional, Any
from datetime import datetime


class TradingMode(Enum):
    BTC_MODE = "btc_mode"
    GOLD_MODE = "gold_mode"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    FAILED = "failed"


@dataclass(frozen=True)
class Symbol:
    base: str
    quote: str

    @property
    def symbol(self) -> str:
        return f"{self.base}/{self.quote}"

    def __str__(self):
        return self.symbol


@dataclass
class Balance:
    currency: str
    free: Decimal
    used: Decimal
    total: Decimal

    @property
    def available_for_trading(self) -> Decimal:
        return self.free


@dataclass
class Order:
    id: str
    symbol: Symbol
    side: OrderSide
    amount: Decimal
    price: Decimal
    status: OrderStatus
    timestamp: datetime
    filled: Decimal = Decimal('0')
    fee: Optional[Decimal] = None
    fee_currency: Optional[str] = None

    @property
    def is_filled(self) -> bool:
        return self.filled >= self.amount

    @property
    def remaining(self) -> Decimal:
        return self.amount - self.filled


@dataclass
class ArbitrageOpportunity:
    symbol: Symbol
    buy_exchange: str
    sell_exchange: str
    buy_price: Decimal
    sell_price: Decimal
    amount: Decimal
    profit_usd: Decimal
    profit_percent: Decimal
    timestamp: datetime

    @property
    def is_profitable(self) -> bool:
        return self.profit_usd > 0 and self.profit_percent > Decimal('0.5')  # 0.5% minimum

    @property
    def profit_after_fees(self) -> Decimal:
        # Will be calculated by fee manager
        return self.profit_usd


@dataclass
class MacroSignal:
    timestamp: datetime
    mode: TradingMode
    confidence: Decimal
    source: str = "tradingview"

    def is_valid(self) -> bool:
        age = datetime.utcnow() - self.timestamp
        return age.seconds < 3600  # Valid for 1 hour


@dataclass
class TradingThresholds:
    min_arbitrage_profit_pct: Decimal = Decimal('0.5')
    max_position_size_usd: Decimal = Decimal('10000')
    max_daily_loss_usd: Decimal = Decimal('500')
    emergency_stop_loss_pct: Decimal = Decimal('5.0')
    macro_switch_cooldown_hours: int = 24

    def can_take_position(self, position_usd: Decimal) -> bool:
        return position_usd <= self.max_position_size_usd
