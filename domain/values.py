"""
Value objects - immutable, validated values
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class Amount:
    value: Decimal
    asset: str

    def __str__(self):
        return str(self.value)

@dataclass(frozen=True)
class Price:
    value: Decimal
    exchange: str
    timestamp: float

    def __post_init__(self):
        if self.value <= 0:
            raise ValueError("Price must be positive")

    def spread_to(self, other: 'Price') -> Decimal:
        """Calculate spread between two prices"""
        if self.value == 0:
            return Decimal('0')
        return (other.value - self.value) / self.value * Decimal('100')


@dataclass(frozen=True)
class FeeStructure:
    maker_fee: Decimal
    taker_fee: Decimal
    bnb_discount: Decimal = Decimal('0.05')  # 5% BNB discount

    def get_effective_fee(self, use_bnb: bool = False) -> Decimal:
        """Get fee with BNB discount applied if available"""
        base_fee = self.taker_fee  # Arbitrage uses taker orders
        if use_bnb:
            return base_fee * (Decimal('1') - self.bnb_discount)
        return base_fee


@dataclass(frozen=True)
class OrderConstraints:
    min_order_size_usd: Decimal
    max_order_size_usd: Decimal
    step_size: Decimal  # Exchange precision

    def normalize_amount(self, desired_amount: Decimal) -> Decimal:
        """Round to exchange step size"""
        return (desired_amount // self.step_size) * self.step_size

    def is_valid_size(self, amount_usd: Decimal) -> bool:
        return self.min_order_size_usd <= amount_usd <= self.max_order_size_usd
