"""
Risk management and health monitoring
CRITICAL: Detects silent failures without blocking Q-Bot
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Callable, Optional
from decimal import Decimal

from domain.aggregates import ExchangeHealth, Portfolio
from domain.entities import TradingThresholds

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Non-blocking health monitor - runs in separate thread"""

    def __init__(self, portfolio: Portfolio, alert_callback: Callable):
        self.portfolio = portfolio
        self.alert_callback = alert_callback
        self.exchange_health: Dict[str, ExchangeHealth] = {}
        self.thresholds = TradingThresholds()
        self._stop_event = asyncio.Event()
        self._check_interval = 30  # seconds

    async def start(self):
        """Start monitoring loop"""
        logger.info(f"Health monitor started (checking every {self._check_interval}s)")
        while not self._stop_event.is_set():
            try:
                await self._check_all_systems()
                await asyncio.sleep(self._check_interval)
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await self.alert_callback("health_monitor_error", str(e))

    def stop(self):
        self._stop_event.set()

    async def _check_all_systems(self):
        """Check all exchanges, positions, and risk limits"""
        tasks = [
            self._check_exchange_heartbeats(),
            self._check_position_limits(),
            self._check_daily_loss_limits(),
            self._check_api_response_times(),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_exchange_heartbeats(self):
        """Verify all exchanges are alive"""
        for exchange_name, health in self.exchange_health.items():
            if not health.is_alive():
                await self.alert_callback(
                    "exchange_timeout",
                    f"{exchange_name} not responding for 60+ seconds"
                )
                # Don't restart Q-Bot's exchanges automatically - alert only

    async def _check_position_limits(self):
        """Ensure no position exceeds thresholds"""
        for symbol, amount in self.portfolio.positions.items():
            # Get current price from scanner (simplified)
            position_value_usd = amount * Decimal('50000')  # Placeholder BTC price
            if not self.thresholds.can_take_position(position_value_usd):
                await self.alert_callback(
                    "position_limit_exceeded",
                    f"{symbol} position ${position_value_usd} exceeds limit"
                )

    async def _check_daily_loss_limits(self):
        """Track daily P&L"""
        # Would need to track daily P&L separately
        pass

    async def _check_api_response_times(self):
        """Alert on slow API responses"""
        for exchange_name, health in self.exchange_health.items():
            if health.api_response_time_ms > 5000:  # 5 seconds is too slow
                await self.alert_callback(
                    "slow_api_response",
                    f"{exchange_name} responding in {health.api_response_time_ms}ms"
                )

    def record_heartbeat(self, exchange_name: str, response_time_ms: int):
        """Record heartbeat from exchange without blocking"""
        self.exchange_health[exchange_name] = ExchangeHealth(
            exchange_name=exchange_name,
            last_heartbeat=datetime.utcnow(),
            api_response_time_ms=response_time_ms
        )

    def record_error(self, exchange_name: str, error: str):
        """Track errors for circuit breaking"""
        if exchange_name not in self.exchange_health:
            return

        health = self.exchange_health[exchange_name]
        health.errors_last_hour += 1
        health.is_healthy = health.errors_last_hour < 10  # More than 10 errors/hour = unhealthy


class RiskLimiter:
    """Non-blocking risk checks for Q-Bot"""

    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio
        self.thresholds = TradingThresholds()

    def can_execute_arbitrage(self, opportunity: 'ArbitrageOpportunity') -> tuple[bool, str]:
        """
        Fast check for Q-Bot - returns immediately, no external calls
        """
        if not opportunity.is_profitable:
            return False, "Not profitable after fees"

        if opportunity.profit_percent < self.thresholds.min_arbitrage_profit_pct:
            return False, "Profit below minimum threshold"

        # Check position size (fast approximation)
        position_value = opportunity.amount * opportunity.buy_price
        if position_value > self.thresholds.max_position_size_usd:
            return False, "Position size exceeds limit"

        return True, "OK"
