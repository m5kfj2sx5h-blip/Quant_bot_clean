import pandas as pd
import numpy as np
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)

class PerformanceAnalyzer:
    """Analyzes trading performance without blocking"""

    def __init__(self, portfolio: Any = None):
        self.portfolio = portfolio
        self.trades: List[Dict] = []
        self.last_update = datetime.min

    def record_trade(self, symbol: str, profit_usd: Decimal, duration_seconds: float,
                     exchange_pair: str, trade_type: str = 'ARB'):
        """Record a completed trade"""
        self.trades.append({
            'timestamp': datetime.utcnow(),
            'symbol': symbol,
            'profit_usd': float(profit_usd),
            'duration_seconds': duration_seconds,
            'exchange_pair': exchange_pair,
            'type': trade_type
        })

        # Keep only last 1000 trades
        if len(self.trades) > 1000:
            self.trades = self.trades[-1000:]

    def get_stats(self) -> Dict[str, Any]:
        """Get performance stats"""
        if not self.trades:
            return self._empty_stats()

        df = pd.DataFrame(self.trades)

        return {
            'total_trades': len(self.trades),
            'total_profit_usd': df['profit_usd'].sum(),
            'avg_profit_per_trade': df['profit_usd'].mean(),
            'win_rate': (df['profit_usd'] > 0).mean(),
            'avg_duration_seconds': df['duration_seconds'].mean(),
            'best_trade': df['profit_usd'].max(),
            'worst_trade': df['profit_usd'].min(),
            'sharpe_ratio': self._calculate_sharpe_ratio(df),
            'last_24h_trades': len(df[df['timestamp'] > datetime.utcnow() - timedelta(hours=24)]),
            'last_24h_profit': df[df['timestamp'] > datetime.utcnow() - timedelta(hours=24)]['profit_usd'].sum(),
        }

    def _calculate_sharpe_ratio(self, df: pd.DataFrame) -> float:
        """Calculate Sharpe ratio (simplified)"""
        if len(df) < 10:
            return 0.0

        returns = pd.Series(df['profit_usd'].values)
        if returns.std() == 0:
            return 0.0

        return float(returns.mean() / returns.std())

    def _empty_stats(self) -> Dict[str, Any]:
        return {
            'total_trades': 0,
            'total_profit_usd': 0.0,
            'avg_profit_per_trade': 0.0,
            'win_rate': 0.0,
            'avg_duration_seconds': 0.0,
            'best_trade': 0.0,
            'worst_trade': 0.0,
            'sharpe_ratio': 0.0,
            'last_24h_trades': 0,
            'last_24h_profit': 0.0,
        }
