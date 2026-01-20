"""
Professional utility functions for quantitative trading
"""

import time
import math
import random
from typing import Optional, Union, Dict, Any, List, Tuple
import datetime
import statistics
import numpy as np

# ========== FINANCIAL CALCULATIONS ==========

def format_currency(
    amount: float,
    currency: str = 'USD',
    precision: int = 2
) -> str:
    """
    Professional currency formatting
    
    Args:
        amount: Amount to format
        currency: Currency code
        precision: Decimal precision
        
    Returns:
        Formatted currency string
    """
    if currency == 'USD':
        return f"${amount:,.{precision}f}"
    elif currency == 'BTC':
        return f"₿{amount:.8f}"
    else:
        return f"{amount:,.{precision}f} {currency}"

def calculate_percentage(
    part: float,
    whole: float,
    precision: int = 2
) -> float:
    """
    Calculate percentage with precision
    
    Args:
        part: Part value
        whole: Whole value
        precision: Decimal precision
        
    Returns:
        Percentage
    """
    if whole == 0:
        return 0.0
    percentage = (part / whole) * 100
    return round(percentage, precision)

def calculate_spread_percentage(
    bid: float,
    ask: float,
    precision: int = 4
) -> float:
    """
    Calculate bid-ask spread percentage
    
    Args:
        bid: Bid price
        ask: Ask price
        precision: Decimal precision
        
    Returns:
        Spread percentage
    """
    if bid == 0 or ask == 0:
        return 0.0
    spread = ((ask - bid) / bid) * 100
    return round(spread, precision)

def calculate_arbitrage_profit(
    buy_price: float,
    sell_price: float,
    amount: float,
    buy_fee: float = 0.001,
    sell_fee: float = 0.001
) -> Tuple[float, float]:
    """
    Calculate arbitrage profit after fees
    
    Args:
        buy_price: Buy price
        sell_price: Sell price
        amount: Trade amount
        buy_fee: Buy fee percentage
        sell_fee: Sell fee percentage
        
    Returns:
        Tuple of (gross_profit, net_profit)
    """
    gross_profit = (sell_price - buy_price) * amount
    buy_fee_amount = buy_price * amount * buy_fee
    sell_fee_amount = sell_price * amount * sell_fee
    net_profit = gross_profit - buy_fee_amount - sell_fee_amount
    
    return round(gross_profit, 2), round(net_profit, 2)

# ========== TIME AND DATE UTILITIES ==========

def exponential_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True
) -> float:
    """
    Professional exponential backoff with jitter
    
    Args:
        attempt: Attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Add random jitter
        
    Returns:
        Delay in seconds
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    
    if jitter:
        # Add ±25% jitter
        jitter_factor = 0.75 + (random.random() * 0.5)
        delay *= jitter_factor
    
    return round(delay, 2)

def format_timestamp(
    timestamp: Optional[float] = None,
    format_str: str = '%Y-%m-%d %H:%M:%S'
) -> str:
    """
    Format timestamp for display
    
    Args:
        timestamp: Unix timestamp (None for current)
        format_str: Datetime format string
        
    Returns:
        Formatted timestamp
    """
    if timestamp is None:
        timestamp = time.time()
    
    dt = datetime.datetime.fromtimestamp(timestamp)
    return dt.strftime(format_str)

def timeit(func):
    """Decorator to measure function execution time"""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"{func.__name__} took {end - start:.4f} seconds")
        return result
    return wrapper

# ========== MATH AND STATISTICS ==========

def safe_divide(
    numerator: float,
    denominator: float,
    default: float = 0.0
) -> float:
    """
    Safe division with default on zero denominator
    
    Args:
        numerator: Numerator
        denominator: Denominator
        default: Default value
        
    Returns:
        Division result or default
    """
    if denominator == 0:
        return default
    return numerator / denominator

def truncate_to_precision(
    value: float,
    precision: int = 8
) -> float:
    """
    Truncate float to specified precision
    
    Args:
        value: Value to truncate
        precision: Decimal precision
        
    Returns:
        Truncated value
    """
    factor = 10 ** precision
    return math.floor(value * factor) / factor

def calculate_volatility(
    prices: List[float],
    annualized: bool = True
) -> float:
    """
    Calculate price volatility
    
    Args:
        prices: List of prices
        annualized: Annualize the volatility
        
    Returns:
        Volatility
    """
    if len(prices) < 2:
        return 0.0
    
    returns = np.diff(prices) / prices[:-1]
    volatility = np.std(returns)
    
    if annualized:
        # Assuming daily data, annualize with √252
        volatility *= math.sqrt(252)
    
    return volatility

# ========== DATA STRUCTURE UTILITIES ==========

def merge_dicts(
    dict1: Dict[str, Any],
    dict2: Dict[str, Any],
    deep: bool = False
) -> Dict[str, Any]:
    """
    Merge dictionaries (dict2 overwrites dict1)
    
    Args:
        dict1: First dictionary
        dict2: Second dictionary
        deep: Deep merge for nested dictionaries
        
    Returns:
        Merged dictionary
    """
    if not deep:
        result = dict1.copy()
        result.update(dict2)
        return result
    
    # Deep merge
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value, deep=True)
        else:
            result[key] = value
    return result

def filter_dict(
    data: Dict[str, Any],
    keys: List[str]
) -> Dict[str, Any]:
    """
    Filter dictionary to only include specified keys
    
    Args:
        data: Input dictionary
        keys: Keys to include
        
    Returns:
        Filtered dictionary
    """
    return {k: data[k] for k in keys if k in data}

# ========== EXCEPTION CLASSES ==========

class RetryableError(Exception):
    """Error that can be retried"""
    pass

class FatalError(Exception):
    """Fatal error that should stop execution"""
    pass

class InsufficientFundsError(Exception):
    """Insufficient funds for trade"""
    pass

class ExchangeError(Exception):
    """Exchange API error"""
    pass