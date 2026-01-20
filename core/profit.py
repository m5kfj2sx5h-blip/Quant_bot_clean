from decimal import Decimal, getcontext
from typing import Dict, Optional

getcontext().prec = 28
getcontext().rounding = "ROUND_HALF_EVEN"

MIN_PROFIT_THRESHOLD = Decimal('0.005')  # Tweak #1: 0.5% baseline net profit

def calculate_gross_profit(buy_price: Decimal, sell_price: Decimal, amount: Decimal) -> Decimal:
    """Calculate gross profit before fees and slippage."""
    return (sell_price - buy_price) * amount

def apply_fees(gross: Decimal, fee_buy: Decimal, fee_sell: Decimal) -> Decimal:
    """Apply buy and sell fees."""
    return gross - (gross * fee_buy) - (gross * fee_sell)

def calculate_net_profit(
    buy_price: Decimal,
    sell_price: Decimal,
    amount: Decimal,
    fee_buy: Decimal,
    fee_sell: Decimal,
    slippage: Decimal = Decimal('0'),
    transfer_cost: Decimal = Decimal('0')
) -> Decimal:
    """
    Calculate net profit with baseline check.
    Returns 0 if below 0.5% threshold (tweak #1).
    """
    gross = calculate_gross_profit(buy_price, sell_price, amount)
    after_fees = apply_fees(gross, fee_buy, fee_sell)
    net = after_fees - (after_fees * slippage) - transfer_cost

    # Tweak #1: Enforce baseline 0.5% net
    if net / (buy_price * amount) < MIN_PROFIT_THRESHOLD:
        return Decimal('0')

    return net

def estimate_slippage(order_book: Dict, trade_size: Decimal, side: str = 'buy') -> Decimal:
    """Estimate slippage from order book (placeholder - add top 5 walk later)."""
    # From your order_executor: simple approximation
    if not order_book or side + 's' not in order_book:
        return Decimal('0')
    levels = order_book[side + 's'][:5]  # top 5 levels
    if not levels:
        return Decimal('0')
    avg_price = sum(level['price'] for level in levels) / Decimal(len(levels))
    return (avg_price - order_book[side + 's'][0]['price']) / order_book[side + 's'][0]['price']