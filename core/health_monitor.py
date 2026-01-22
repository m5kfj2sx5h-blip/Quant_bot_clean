# !/usr/bin/env python3
"""
RISK MANAGER, HEALTH MONITOR & PERFORMANCE TELEMETRY SYSTEM
Version: 3.0.2 | Component: System Health & Optimization
Author: |\/||| | Last Updated: 2026-01-22 00:12

Features:
- Real-time performance metrics collection
- Adaptive cycle time optimization
- API error tracking and rate limiting detection
- Memory leak detection and prevention
- Trade execution quality monitoring
- Network latency tracking
- Self-healing recommendations
"""

import json
import time
import os
import pandas as pd
import psutil
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Callable, List, Any, Optional
from decimal import Decimal

from domain.aggregates import ExchangeHealth, Portfolio
from domain.entities import TradingThresholds

logger = logging.getLogger(__name__)

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    level: AlertLevel
    message: str
    timestamp: float
    source: str = ""
    data: Dict[str, Any] = field(default_factory=dict)



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
        logger.info(f"❌ Health monitor started (checking every {self._check_interval}s)")
        while not self._stop_event.is_set():
            try:
                await self._check_all_systems()
                await asyncio.sleep(self._check_interval)
            except Exception as e:
                logger.error(f"❌ Health monitor error: {e}")
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
                    f"⚠️ {exchange_name} not responding for 60+ seconds"
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
                    f"⚠️ {symbol} position ${position_value_usd} exceeds limit"
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
                    f"⚠️ {exchange_name} responding in {health.api_response_time_ms}ms"
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



class HealthMonitor:
    """
    Monitors overall system health including exchanges, network, and resources.
    Provides adaptive recommendations for optimization.
    """

    def __init__(self, config, logger=None):
        """Initialize health monitor with configuration."""
        self.config = self._load_config(config)
        self.logger = logger or self._setup_monitoring_logger()
        self.start_time = time.time()

        # Initialize monitoring state with proper data structures
        self.api_errors = defaultdict(deque)
        self.api_successes = defaultdict(deque)
        self.latency_metrics = defaultdict(deque)
        self.trade_executions = deque(maxlen=200)
        self.resource_usage = deque(maxlen=500)
        self.rebalance_suggestions = deque(maxlen=100)
        self.active_alerts = deque(maxlen=50)

        # Performance tracking
        self.cycle_times = deque(maxlen=100)
        self.error_rates = defaultdict(float)
        self.last_report_time = time.time()

        # Initialize default configuration
        self.default_config = {
            'health_check_interval': 300,
            'metrics_report_interval': 60,
            'detailed_report_interval': 3600,
            'alert_on_api_error_rate': 0.3,
            'alert_on_memory_growth_mb': 10,
            'alert_on_high_cpu_percent': 80,
            'alert_on_slow_cycle_time': 2.0,
            'performance_sample_size': 100,
            'telemetry_enabled': True
        }

        # Merge with provided config
        self.monitoring_config = self._merge_configs(self.config)
        self.logger.info(
            f"✅ Health Monitor initialized (window_size={self.monitoring_config['performance_sample_size']})")

    def _load_config(self, config):
        """Load the health monitoring configuration from a file or dict."""
        if isinstance(config, dict):
            return config
        elif isinstance(config, str):
            try:
                with open(config, 'r') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"❌ Health config load failed, using defaults: {e}")
                return self.default_config
        else:
            self.logger.warning(f"❌ Health config load failed, unexpected type {type(config)}, using defaults")
            return self.default_config

    def _merge_configs(self, config: Dict) -> Dict:
        """Merge default config with provided config."""
        merged = self.default_config.copy()
        if 'monitoring' in config:
            merged.update(config['monitoring'])
        return merged

    def _setup_monitoring_logger(self):
        """Setup dedicated logger for monitoring."""
        logger = logging.getLogger('health_monitor')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def adjust_cycle_time(self, current_cycle_time: float, mode: str = "high_latency") -> float:
        """Dynamically adjust cycle time based on performance."""
        self.cycle_times.append(current_cycle_time)
        if len(self.cycle_times) > self.monitoring_config['performance_sample_size']:
            self.cycle_times.popleft()

        return self._calculate_adaptive_sleep(current_cycle_time, mode)

    def _calculate_adaptive_sleep(self, current_cycle_time: float, mode: str) -> float:
        """Calculate adaptive sleep time based on current performance."""
        base_delay = 2.0  # Default base delay

        if mode == "low_latency" and current_cycle_time < 0.1:
            return max(0.05, base_delay * 0.5)
        elif current_cycle_time > 1.0:
            return min(10.0, base_delay * 2)

        return base_delay

    def log_api_error(self, exchange_id: str, endpoint: str, error: str):
        """Log an API error for an exchange."""
        self.api_errors[exchange_id].append({
            'timestamp': time.time(),
            'endpoint': endpoint,
            'error': error
        })

        # Trim old errors
        if len(self.api_errors[exchange_id]) > 100:
            self.api_errors[exchange_id].popleft()

    def log_api_success(self, exchange_id: str, endpoint: str, latency_ms: float):
        """Log a successful API call."""
        self.api_successes[exchange_id].append({
            'timestamp': time.time(),
            'endpoint': endpoint,
            'latency_ms': latency_ms
        })

    def log_trade_execution(self, trade_details: Dict):
        """Log trade execution details."""
        self.trade_executions.append({
            'timestamp': time.time(),
            'details': trade_details
        })

    def log_network_latency(self, source: str, target: str, latency_ms: float):
        """Log network latency between points."""
        key = f"{source}_{target}"
        self.latency_metrics[key].append({
            'timestamp': time.time(),
            'latency_ms': latency_ms
        })

    def log_exchange_latency(self, exchange_id: str, latency_ms: float):
        """Log exchange-specific latency."""
        self.log_network_latency('system', exchange_id, latency_ms)

    def log_rebalance_suggestion(self, suggestion: Dict):
        """Log a rebalance suggestion."""
        self.rebalance_suggestions.append({
            'timestamp': time.time(),
            'suggestion': suggestion
        })

    def update_resource_usage(self):
        """Update system resource usage metrics."""
        self.resource_usage.append({
            'timestamp': time.time(),
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'memory_mb': psutil.Process().memory_info().rss / 1024 / 1024,
            'active_exchanges': len(self.api_successes)
        })

    def _calculate_error_rate(self, exchange_id: str) -> float:
        """Calculate error rate for an exchange."""
        if exchange_id not in self.api_errors:
            return 0.0

        # Calculate rates for last hour
        cutoff = time.time() - 3600
        recent_errors = sum(1 for e in self.api_errors[exchange_id] if e['timestamp'] > cutoff)
        recent_successes = sum(1 for s in self.api_successes.get(exchange_id, []) if s['timestamp'] > cutoff)

        total_calls = recent_errors + recent_successes
        if total_calls == 0:
            return 0.0

        return recent_errors / total_calls

    def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status of the system."""
        health_status = {
            'overall_health': HealthStatus.HEALTHY.value,
            'exchanges': {},
            'system_resources': {},
            'performance_metrics': {},
            'recommendations': [],
            'active_alerts': list(self.active_alerts)
        }

        # Check exchange health
        for exchange_id in set(list(self.api_errors.keys()) + list(self.api_successes.keys())):
            error_rate = self._calculate_error_rate(exchange_id)

            if error_rate > self.monitoring_config['alert_on_api_error_rate']:
                exchange_health = HealthStatus.CRITICAL.value
                health_status['overall_health'] = HealthStatus.DEGRADED.value
                self.active_alerts.append(Alert(
                    level=AlertLevel.ERROR,
                    message=f"❌ High error rate on {exchange_id}: {error_rate:.1%}",
                    timestamp=time.time(),
                    source=exchange_id,
                    data={'error_rate': error_rate}
                ))
            elif error_rate > 0.1:
                exchange_health = HealthStatus.DEGRADED.value
                health_status['overall_health'] = HealthStatus.DEGRADED.value
            else:
                exchange_health = HealthStatus.HEALTHY.value

            health_status['exchanges'][exchange_id] = {
                'health': exchange_health,
                'error_rate': error_rate,
                'recent_errors': sum(
                    1 for e in self.api_errors.get(exchange_id, []) if time.time() - e['timestamp'] < 300),
                'recent_successes': sum(
                    1 for s in self.api_successes.get(exchange_id, []) if time.time() - s['timestamp'] < 300)
            }

        # Check system resources
        if self.resource_usage:
            latest = self.resource_usage[-1]
            health_status['system_resources'] = {
                'cpu_percent': latest['cpu_percent'],
                'memory_mb': latest['memory_mb'],
                'active_exchanges': latest['active_exchanges']
            }

            if latest['cpu_percent'] > self.monitoring_config['alert_on_high_cpu_percent']:
                health_status['overall_health'] = HealthStatus.DEGRADED.value
                self.active_alerts.append(Alert(
                    level=AlertLevel.WARNING,
                    message=f"⚠️ High CPU usage: {latest['cpu_percent']}%",
                    timestamp=time.time(),
                    source='system',
                    data={'cpu_percent': latest['cpu_percent']}
                ))

            if latest['memory_mb'] > 1024:  # 1GB threshold
                health_status['overall_health'] = HealthStatus.DEGRADED.value

        # Performance metrics
        if self.cycle_times:
            cycle_times_list = list(self.cycle_times)
            health_status['performance_metrics'] = {
                'avg_cycle_time': statistics.mean(cycle_times_list) if cycle_times_list else 0,
                'min_cycle_time': min(cycle_times_list) if cycle_times_list else 0,
                'max_cycle_time': max(cycle_times_list) if cycle_times_list else 0,
                'std_cycle_time': statistics.stdev(cycle_times_list) if len(cycle_times_list) > 1 else 0,
                'sample_size': len(cycle_times_list)
            }

            avg_cycle = health_status['performance_metrics']['avg_cycle_time']
            if avg_cycle > self.monitoring_config['alert_on_slow_cycle_time']:
                health_status['overall_health'] = HealthStatus.DEGRADED.value

        # Generate recommendations
        health_status['recommendations'] = self._generate_recommendations(health_status)

        return health_status

    def check_system_health(self):
        """
        COMPATIBILITY METHOD FOR system.py
        Returns True if system is healthy, False otherwise.
        Added to match the interface expected by the new orchestrator.
        """
        health_status = self.get_health_status()
        # Return True only if overall health is 'healthy'
        return health_status['overall_health'] == HealthStatus.HEALTHY.value

    def _perform_health_check(self) -> Dict[str, Any]:
        """Perform detailed health check (used internally)."""
        return self.get_health_status()

    def _generate_recommendations(self, health_status: Dict) -> List[str]:
        """Generate recommendations based on health status."""
        recommendations = []

        # Check for high error rates
        for exchange_id, exchange_data in health_status['exchanges'].items():
            if exchange_data['error_rate'] > 0.2:
                recommendations.append(
                    f"⚠️ High error rate on {exchange_id} ({exchange_data['error_rate']:.1%}). "
                    f"⚠️ Consider reducing trade frequency or investigating connectivity."
                )

        # Check system resources
        sys_resources = health_status.get('system_resources', {})
        if sys_resources.get('cpu_percent', 0) > 70:
            recommendations.append(
                f"⚠️ High CPU usage ({sys_resources['cpu_percent']}%). "
                f"⚠️ Consider increasing cycle delay or optimizing code."
            )

        if sys_resources.get('memory_mb', 0) > 800:
            recommendations.append(
                f"⚠️ High memory usage ({sys_resources['memory_mb']:.1f}MB). "
                f"⚠️ Consider clearing caches or reducing data retention."
            )

        # Check performance
        perf_metrics = health_status.get('performance_metrics', {})
        if perf_metrics.get('avg_cycle_time', 0) > 1.5:
            recommendations.append(
                f"⚠️ Slow cycle times ({perf_metrics['avg_cycle_time']:.2f}s). "
                f"⚠️ Consider optimizing data fetching or reducing exchange calls."
            )

        return recommendations

    def _get_active_alerts(self) -> List[Alert]:
        """Get active alerts based on current state."""
        return list(self.active_alerts)

    def generate_report(self, report_type: str = "summary") -> Dict[str, Any]:
        """Generate a monitoring report."""
        health_status = self.get_health_status()

        report = {
            'timestamp': time.time(),
            'report_type': report_type,
            'uptime_seconds': time.time() - self.start_time,
            'health_status': health_status,
            'active_alerts': [alert.__dict__ for alert in self.active_alerts],
            'rebalance_suggestions': list(self.rebalance_suggestions)
        }

        if report_type == "detailed":
            report.update({
                'api_errors_summary': {k: len(v) for k, v in self.api_errors.items()},
                'latency_distribution': self._get_distribution(),
                'resource_trend': list(self.resource_usage)[-20:] if self.resource_usage else []
            })

        return report

    def _get_distribution(self) -> Dict[str, List[float]]:
        """Get latency distribution across all tracked paths."""
        distribution = {}
        for key, metrics in self.latency_metrics.items():
            if metrics:
                latencies = [m['latency_ms'] for m in metrics]
                distribution[key] = [
                    min(latencies) if latencies else 0,
                    max(latencies) if latencies else 0,
                    statistics.mean(latencies) if latencies else 0
                ]
        return distribution

    def _get_aggregated_distribution(self) -> Dict[str, float]:
        """Get aggregated distribution statistics."""
        all_latencies = []
        for metrics in self.latency_metrics.values():
            all_latencies.extend([m['latency_ms'] for m in metrics])

        if not all_latencies:
            return {'min': 0, 'max': 0, 'avg': 0, 'p95': 0}

        sorted_latencies = sorted(all_latencies)
        return {
            'min': sorted_latencies[0],
            'max': sorted_latencies[-1],
            'avg': statistics.mean(sorted_latencies),
            'p95': sorted_latencies[int(len(sorted_latencies) * 0.95)]
        }

    def save_report(self, filepath: str = "health_report.json"):
        """Save current report to file."""
        report = self.generate_report("detailed")
        try:
            with open(filepath, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            self.logger.info(f"✅ Health report saved to {filepath}")
        except Exception as e:
            self.logger.error(f"❌ Failed to save health report: {e}")

# Example usage
if __name__ == "__main__":
    # Test the health monitor
    monitor = HealthMonitor({"monitoring": {"health_check_interval": 60}})

    # Simulate some metrics
    monitor.log_api_success("binance", "ticker", 45.2)
    monitor.log_api_error("kraken", "orderbook", "Timeout")
    monitor.log_exchange_latency("coinbase", 120.5)

    # Generate report
    report = monitor.generate_report()
    print(json.dumps(report, indent=2))


"""
Performance analysis for the bot system
Runs in separate thread, doesn't block Q-Bot
"""

class PerformanceAnalyzer:
    """Analyzes trading performance without blocking"""

    def __init__(self, portfolio: 'Portfolio'):
        self.portfolio = portfolio
        self.trades: List[Dict] = []
        self.last_update = datetime.min

    def record_trade(self, symbol: str, profit_usd: Decimal, duration_seconds: float,
                     exchange_pair: str):
        """Record a completed arbitrage trade"""
        self.trades.append({
            'timestamp': datetime.utcnow(),
            'symbol': symbol,
            'profit_usd': float(profit_usd),
            'duration_seconds': duration_seconds,
            'exchange_pair': exchange_pair,
        })

        # Keep only last 1000 trades
        if len(self.trades) > 1000:
            self.trades = self.trades[-1000:]

    def get_stats(self) -> Dict[str, Any]:
        """Get performance stats (called by dashboard)"""
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
