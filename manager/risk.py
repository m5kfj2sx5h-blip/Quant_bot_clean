import logging
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple
from domain.entities import TradingThresholds, ArbitrageOpportunity
from domain.aggregates import Portfolio

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Dedicated Risk Manager for the trading system.
    Handles position sizing, loss limits, and emergency exits.
    """
    def __init__(self, portfolio: Portfolio, config: Dict = None):
        self.portfolio = portfolio
        self.config = config or {}
        self.thresholds = TradingThresholds()
        self.max_trade_risk_pct = Decimal('0.01') # 1% allotted capital per trade
        
    def can_execute_arbitrage(self, opportunity: ArbitrageOpportunity) -> Tuple[bool, str]:
        """
        Final risk check before Q-Bot pulls the trigger.
        """
        if not opportunity.is_profitable:
            return False, "⚠️ Not profitable after fees"

        if opportunity.profit_percent < self.thresholds.min_arbitrage_profit_pct:
            return False, "⚠️ Profit below minimum threshold"

        # Check position size
        position_value = opportunity.amount * opportunity.buy_price
        if position_value > self.thresholds.max_position_size_usd:
            return False, "⚠️ Position size exceeds limit"

        return True, "OK"

    def check_emergency_exit(self, symbol: str, current_price: Decimal, buy_price: Decimal, allotted_capital: Decimal) -> bool:
        """
        Implements the 1% risk rule: 
        If the trade goes against us by more than 1% of ALLOTTED capital, close the trade.
        """
        if buy_price <= 0 or allotted_capital <= 0:
            return False
            
        unrealized_pnl_usd = (current_price - buy_price) * (allotted_capital / buy_price)
        max_loss_usd = allotted_capital * self.max_trade_risk_pct
        
        if unrealized_pnl_usd < -max_loss_usd:
            logger.critical(f"🚨 EMERGENCY EXIT: {symbol} P&L ${unrealized_pnl_usd:.2f} hit 1% risk limit (${max_loss_usd:.2f})")
            return True
            
        return False

    def get_max_position_size(self, tpv: Decimal) -> Decimal:
        """Calculate max position size based on TPV."""
        return tpv * Decimal('0.05') # 5% of TPV default
