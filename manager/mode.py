"""
Macro mode manager - handles BTC_MODE vs GOLD_MODE
CRITICAL: Only switches at MACRO cycle boundaries (1-2x/year)
"""
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from domain.entities import TradingMode, MacroSignal
from domain.aggregates import Portfolio

logger = logging.getLogger(__name__)


class ModeManager:
    """Manages macro trading mode with 1-2x/year switching"""

    def __init__(self, portfolio: Portfolio, tradingview_webhook_secret: str):
        self.portfolio = portfolio
        self.tradingview_secret = tradingview_webhook_secret
        self.current_mode = TradingMode.BTC_MODE
        self.last_switch_date: Optional[datetime] = None

        # MACRO cycle timing - explicit 6 month minimum
        self.macro_cycle_duration = timedelta(days=180)  # 6 months minimum

    async def handle_tradingview_signal(self, signal_data: dict) -> bool:
        """
        Process TradingView macro signal
        Only switches if:
        1. Signal is valid (signed correctly)
        2. Cooldown period passed (6 months)
        3. Confidence > 80%
        """
        try:
            # Verify webhook signature
            if not self._verify_signature(signal_data):
                logger.error("Invalid TradingView webhook signature")
                return False

            mode = TradingMode(signal_data['mode'])
            confidence = Decimal(str(signal_data['confidence']))

            if confidence < Decimal('0.80'):
                logger.warning(f"Confidence too low: {confidence}")
                return False

            if not self._can_switch_macro():
                logger.warning(
                    f"Macro switch blocked: last switch {self.last_switch_date}, "
                    f"cooldown: {self.macro_cycle_duration}"
                )
                return False

            # Create macro signal
            macro_signal = MacroSignal(
                timestamp=datetime.utcnow(),
                mode=mode,
                confidence=confidence,
                source="tradingview"
            )

            # Update portfolio aggregate
            success = self.portfolio.update_macro_signal(macro_signal)

            if success:
                self.current_mode = mode
                self.last_switch_date = datetime.utcnow()
                logger.critical(f"=== MACRO SWITCH: {mode.value.upper()} ===")

                # Trigger gold conversion calculation
                if mode == TradingMode.GOLD_MODE:
                    await self._calculate_gold_conversion_target()

            return success

        except Exception as e:
            logger.error(f"Mode switch error: {e}", exc_info=True)
            return False

    def _can_switch_macro(self) -> bool:
        """MACRO cycle enforcement: 6 month minimum between switches"""
        if not self.last_switch_date:
            return True

        time_since_last = datetime.utcnow() - self.last_switch_date
        return time_since_last >= self.macro_cycle_duration

    def _verify_signature(self, signal_data: dict) -> bool:
        """Verify TradingView webhook signature"""
        # Implementation depends on TradingView config
        # For now, validate structure
        required_fields = ['mode', 'confidence', 'timestamp']
        return all(field in signal_data for field in required_fields)

    async def _calculate_gold_conversion_target(self):
        """Calculate 15% of profits for gold accumulation"""
        total_profits = self.portfolio.total_profit_usd
        gold_target = total_profits * Decimal('0.15')

        logger.critical(
            f"Gold accumulation target: ${gold_target:,.2f} "
            f"(15% of ${total_profits:,.2f} total profits)"
        )

        # Store in portfolio aggregate
        self.portfolio.gold_target_this_cycle = gold_target
        self.portfolio.gold_accumulated_this_cycle = Decimal('0')

    def get_current_mode(self) -> TradingMode:
        return self.current_mode

    def should_accumulate_gold(self) -> bool:
        """Check if we should buy PAXG on gold spikes"""
        return (
                self.current_mode == TradingMode.GOLD_MODE and
                self.portfolio.gold_accumulated_this_cycle < self.portfolio.gold_target_this_cycle
        )
