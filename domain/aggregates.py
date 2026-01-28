"""
Aggregate roots - maintain consistency boundaries
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from domain.entities import Symbol, Balance, Order, TradingMode, MacroSignal


@dataclass
class Portfolio:
    """Root aggregate for entire portfolio state"""
    exchange_balances: Dict[str, Dict[str, Balance]] = field(default_factory=dict)
    open_orders: Dict[str, List[Order]] = field(default_factory=dict)
    positions: Dict[Symbol, Decimal] = field(default_factory=dict)  # symbol -> amount
    total_profit_usd: Decimal = Decimal('0')
    total_trades: int = 0
    winning_trades: int = 0
    total_value_usd: Decimal = Decimal('0')

    # Macro cycle state - CRITICAL: Only changes 1-2x/year
    macro_signal: Optional[MacroSignal] = None
    snapshot_tpv_at_signal: Decimal = Decimal('0')
    gold_accumulated_this_cycle: Decimal = Decimal('0')
    gold_target_this_cycle: Decimal = Decimal('0')
    last_macro_switch: Optional[datetime] = None

    def restore_from_dict(self, data: dict):
        """Restore portfolio state from persistent storage."""
        from decimal import Decimal
        from datetime import datetime
        self.total_profit_usd = Decimal(str(data.get('total_profit_usd', '0')))
        self.total_trades = int(data.get('total_trades', 0))
        self.winning_trades = int(data.get('winning_trades', 0))
        self.snapshot_tpv_at_signal = Decimal(str(data.get('snapshot_tpv_at_signal', '0')))
        self.gold_accumulated_this_cycle = Decimal(str(data.get('gold_accumulated_cycle', '0')))
        self.gold_target_this_cycle = Decimal(str(data.get('gold_target_cycle', '0')))
        if data.get('timestamp'):
            self.last_macro_switch = datetime.fromisoformat(data['timestamp'].replace(' ', 'T'))

    def update_macro_signal(self, signal: MacroSignal) -> bool:
        """Update macro mode with cooldown protection"""
        if not self._can_switch_macro():
            return False

        self.macro_signal = signal
        self.last_macro_switch = datetime.utcnow()

        # Recalculate gold target when macro switches
        if signal.mode == TradingMode.GOLD_MODE:
            profits = self.total_profit_usd
            self.gold_target_this_cycle = profits * Decimal('0.15')  # 15% of profits
        else:
            self.gold_target_this_cycle = Decimal('0')

        return True

    def _can_switch_macro(self) -> bool:
        if not self.last_macro_switch:
            return True

        cooldown = timedelta(hours=24)  # 24 hour cooldown
        return datetime.utcnow() - self.last_macro_switch > cooldown

    def record_arbitrage_profit(self, profit_usd: Decimal):
        """Record profit and update winning trade stats"""
        self.total_profit_usd += profit_usd
        self.total_trades += 1

        if profit_usd > 0:
            self.winning_trades += 1

    def get_win_rate(self) -> Decimal:
        if self.total_trades == 0:
            return Decimal('0')
        return Decimal(str(self.winning_trades / self.total_trades))

    def get_sharpe_ratio(self) -> Decimal:
        # Placeholder - would need P&L history
        return Decimal('1.5')  # Assume good performance

    def should_convert_to_gold(self) -> bool:
        """CRITICAL: Only true at end of MACRO cycle (1-2x/year)"""
        if self.macro_signal and self.macro_signal.mode == TradingMode.GOLD_MODE:
            return self.gold_accumulated_this_cycle < self.gold_target_this_cycle
        return False


@dataclass
class ExchangeHealth:
    """Health status for each exchange"""
    exchange_name: str
    last_heartbeat: datetime
    errors_last_hour: int = 0
    is_healthy: bool = True
    api_response_time_ms: int = 0

    def is_alive(self, timeout_seconds: int = 60) -> bool:
        """Check if exchange is responding"""
        age = datetime.utcnow() - self.last_heartbeat
        return age.seconds < timeout_seconds and self.is_healthy
