import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from domain.entities import TradingMode, MacroSignal
from typing import Optional, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class ModeManager:
    def __init__(self, portfolio: Any, tradingview_webhook_secret: str):
        self.portfolio = portfolio
        self.tradingview_secret = tradingview_webhook_secret
        self.current_mode = TradingMode.BTC_MODE
        self.last_switch_date: Optional[datetime] = None
        self.macro_cycle_duration = timedelta(days=180)

    async def handle_tradingview_signal(self, signal_data: dict) -> bool:
        try:
            if not self._verify_signature(signal_data):
                logger.error("Invalid TradingView webhook signature")
                return False
            
            # Allow strings like 'btc_mode' or 'btc'
            mode_input = signal_data['mode'].lower()
            if mode_input == 'btc':
                mode = TradingMode.BTC_MODE
            elif mode_input == 'gold':
                mode = TradingMode.GOLD_MODE
            else:
                mode = TradingMode(mode_input)

            confidence = Decimal(str(signal_data.get('confidence', 1.0)))
            if confidence < Decimal('0.80'):
                logger.warning(f"Confidence too low: {confidence}")
                return False
            
            if not self._can_switch_macro():
                logger.warning(f"Macro switch blocked: last switch {self.last_switch_date}, cooldown: {self.macro_cycle_duration}")
                return False

            macro_signal = MacroSignal(timestamp=datetime.utcnow(), mode=mode, confidence=confidence, source="tradingview")
            
            success = True
            if self.portfolio:
                success = self.portfolio.update_macro_signal(macro_signal)
            
            if success:
                self.current_mode = mode
                self.last_switch_date = datetime.utcnow()
                logger.critical(f"=== MACRO SWITCH: {mode.value.upper()} ===")
                if mode == TradingMode.GOLD_MODE and self.portfolio:
                    await self._calculate_gold_conversion_target()
                return success
        except Exception as e:
            logger.error(f"Mode switch error: {e}", exc_info=True)
            return False

    def _can_switch_macro(self) -> bool:
        if not self.last_switch_date:
            return True
        time_since_last = datetime.utcnow() - self.last_switch_date
        return time_since_last >= self.macro_cycle_duration

    def _verify_signature(self, signal_data: dict) -> bool:
        required_fields = ['mode', 'confidence', 'timestamp']
        return all(field in signal_data for field in required_fields)

    async def _calculate_gold_conversion_target(self):
        total_profits = self.portfolio.total_profit_usd
        gold_target = total_profits * Decimal('0.15')
        logger.critical(f"Gold accumulation target: ${gold_target:,.2f} (15% of ${total_profits:,.2f} total profits)")
        self.portfolio.gold_target_this_cycle = gold_target
        self.portfolio.gold_accumulated_this_cycle = Decimal('0')

    def get_current_mode(self) -> TradingMode:
        return self.current_mode

    def should_accumulate_gold(self) -> bool:
        return (self.current_mode == TradingMode.GOLD_MODE and self.portfolio.gold_accumulated_this_cycle < self.portfolio.gold_target_this_cycle)