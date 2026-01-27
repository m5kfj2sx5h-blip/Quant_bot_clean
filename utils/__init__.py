"""
UTILS MODULE - Professional utilities for quantitative trading
"""

# Logger exports
from .logger import (
    EnterpriseLogger,
    setup_logger,
    get_logger
)

# Helper exports
from .helpers import (
    # Financial calculations
    format_currency,
    calculate_percentage,
    calculate_spread_percentage,
    calculate_arbitrage_profit,
    
    # Time utilities
    exponential_backoff,
    format_timestamp,
    timeit,
    
    # Math utilities
    safe_divide,
    truncate_to_precision,
    calculate_volatility,
    
    # Data utilities
    merge_dicts,
    filter_dict,
    
    # Exception classes
    RetryableError,
    FatalError,
    InsufficientFundsError,
    ExchangeError
)

__version__ = "1.0.0"
__author__ = "Quantitative Trading Team"

__all__ = [
    # Logger
    'EnterpriseLogger',
    'setup_logger',
    'get_logger',
    
    # Financial
    'format_currency',
    'calculate_percentage',
    'calculate_spread_percentage',
    'calculate_arbitrage_profit',
    
    # Time
    'exponential_backoff',
    'format_timestamp',
    'timeit',
    
    # Math
    'safe_divide',
    'truncate_to_precision',
    'calculate_volatility',
    
    # Data
    'merge_dicts',
    'filter_dict',
    
    # Exceptions
    'RetryableError',
    'FatalError',
    'InsufficientFundsError',
    'ExchangeError'
]

# Optional: Initialize default logger for the module
import logging
_module_logger = logging.getLogger(__name__)
_module_logger.addHandler(logging.NullHandler())