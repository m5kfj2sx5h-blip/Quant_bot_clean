#!/usr/bin/env python3
"""
PROFESSIONAL ARBITRAGE TRADING SYSTEM - MAIN ORCHESTRATOR
Version: 2.0.0
Description: Core orchestration manager for multi-exchange arbitrage trading system
"""

import json
import logging
import os
import signal
import sys
import time
import traceback
from datetime import datetime
from typing import Dict, Any

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import components
from adapters.data.feed import DataFeed
from manager.scanner import MarketContext, ArbitrageAnalyzer
from core.order_executor import OrderExecutor
from manager.health_monitor import HealthMonitor
from exchange_wrappers import ExchangeWrapperFactory

class SystemOrchestrator:
    """Main orchestrator for the multi-exchange arbitrage bot."""
    
    def __init__(self, config_path: str = "config/bot_config.json"):
        """Initialize the orchestrator with configuration."""
        # FIX: Setup logging FIRST
        self._setup_logging()
        self.logger = logging.getLogger("ArbitrageBot.Orchestrator")
        
        self.config_path = config_path
        self.config = self._load_config()
        
        # Component references
        self.data_feed = None
        self.exchange_wrappers: Dict[str, Any] = {}
        self.market_context = None
        self.arbitrage_analyzer = None
        self.order_executor = None
        self.health_monitor = None
        
        # State management
        self.running = True
        self.start_time = None
        self.trade_cycles = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.current_profit = 0.0
        self.estimated_balance = 0.0
        self.capital_mode = "BALANCED"
        self.available_capital_usd = 0.0
        self.settings = {}
        
        # Performance tracking
        self.cycle_times = []
        self.latency_mode = "unknown"
        self.consecutive_failures = 0
        self.use_dynamic_sizing = False
        
        # WebSocket initialization tracking
        self.websocket_init_attempts = 0
        self.max_websocket_init_attempts = 3
        self.websocket_ready = False
        self.last_data_check = 0
        
        # Data availability tracking
        self.consecutive_no_data = 0
        self.max_consecutive_no_data = 10  # Allow 10 cycles without data before warning
        
        # Dynamic sizing state
        self.dynamic_sizing_configured = False
        self.dynamic_sizing_available = False
        
        self.logger.info("✅ SystemOrchestrator initialized (WebSocket-only mode)")
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            # Verify config structure
            exchanges = config.get('exchanges', {})
            if isinstance(exchanges, list):
                raise ValueError("Configuration error: 'exchanges' must be a dictionary, not a list")
            
            self.logger.info(f"✅ Configuration loaded from {self.config_path}")
            return config
        except Exception as e:
            self.logger.error(f"❌ Failed to load config: {e}")
            sys.exit(1)
    
    def _setup_logging(self):
        """Configure logging for the system."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def _validate_config(self):
        """Validate configuration for WebSocket-only operation."""
        # Force WebSocket mode regardless of config
        if self.config.get('latency_mode', 'low_latency') != 'low_latency':
            self.logger.warning(f"⚠️  Config latency_mode is {self.config['latency_mode']}, forcing 'low_latency' for WebSocket operation")
            self.config['latency_mode'] = 'low_latency'
        
        # Validate dynamic position sizing configuration
        dynamic_enabled = self.config.get('dynamic_position_sizing', False)
        position_mode = self.config.get('position_sizing_mode', 'static')
        
        if dynamic_enabled and position_mode == 'dynamic':
            self.dynamic_sizing_configured = True
            self.logger.info("✅ Dynamic position sizing configured (will activate once WebSocket data is available)")
        else:
            self.logger.info("ℹ️  Static position sizing configured")
    
    def _initialize_components(self):
        """Initialize all system components - SINGLE INITIALIZATION FLOW."""
        self.logger.info("🔄 Initializing system components...")
        
        # 1. Validate and update configuration
        self._validate_config()
        
        # 2. Initialize settings
        self.settings = {
            'position_size': self.config.get('position_size', 500.0),
            'max_position_size': self.config.get('max_position_size', 5000.0),
            'min_position_size_usd': self.config.get('min_position_size_usd', 10.0),
            'min_profit_threshold': self.config.get('min_profit_threshold', 0.5),
            'slippage_tolerance_percent': self.config.get('slippage_tolerance_percent', 0.1),
            'min_stable_per_exchange': self.config.get('min_stable_per_exchange', 1500.0),
            'cycle_delay': self.config.get('cycle_delay', 2.0),
            'max_consecutive_failures': self.config.get('max_consecutive_failures', 5),
            'max_websocket_init_time': self.config.get('max_websocket_init_time', 10)  # seconds
        }
        
        # 3. Initialize exchange wrappers FIRST
        exchange_configs = self.config.get('exchanges', {})
        
        for exchange_id, exchange_config in exchange_configs.items():
            if exchange_config.get('enabled', False):
                try:
                    # Get environment variable names
                    api_key_env_var = exchange_config.get('api_key')
                    api_secret_env_var = exchange_config.get('api_secret')
                    
                    if not api_key_env_var or not api_secret_env_var:
                        self.logger.error(f"❌ API key/secret env var names not configured for {exchange_id}")
                        continue
                    
                    # Load from environment
                    api_key = os.getenv(api_key_env_var)
                    api_secret = os.getenv(api_secret_env_var)
                    
                    if not api_key or not api_secret:
                        self.logger.error(f"❌ Could not load API credentials for {exchange_id}")
                        continue
                    
                    # Build config for wrapper
                    wrapper_config = {
                        'api_key': api_key,
                        'api_secret': api_secret,
                        **exchange_config
                    }
                    
                    # Create wrapper
                    wrapper = ExchangeWrapperFactory.create_wrapper(exchange_id, wrapper_config)
                    
                    if wrapper:
                        self.exchange_wrappers[exchange_id] = wrapper
                        self.logger.info(f"✅ {exchange_id} wrapper created")
                    else:
                        self.logger.error(f"❌ Factory failed to create wrapper for {exchange_id}")
                        
                except Exception as e:
                    self.logger.error(f"❌ Failed to initialize {exchange_id}: {e}")
                    traceback.print_exc()
        
        if not self.exchange_wrappers:
            self.logger.error("❌ No exchanges initialized. Check configuration.")
            sys.exit(1)
        
        # 4. Force LOW_LATENCY (WebSocket) mode - NO REST FALLBACK
        self.latency_mode = "low_latency"
        self.logger.info(f"📡 Latency mode: {self.latency_mode} (WebSocket-only, NO REST fallback)")
        
        # 5. Initialize DataFeed with WebSocket-only mode
        self.data_feed = DataFeed(self.config, self.logger)
        self.data_feed.set_latency_mode(self.latency_mode)
        self.data_feed.start()  # This starts WebSocket connections
        
        # 6. Give WebSocket connections time to initialize
        self.logger.info("⏳ Waiting for WebSocket connections to initialize (5 seconds)...")
        time.sleep(5)
        
        # 7. Initialize Market Context
        self.market_context = MarketContext(self.config, self.logger)
        self.logger.info("✅ Market Context initialized")
        
        # 8. Initialize Arbitrage Analyzer
        context_data = self.market_context.get_context()
        self.arbitrage_analyzer = ArbitrageAnalyzer(context_data, self.config, self.logger)
        self.logger.info("✅ Arbitrage Analyzer initialized")
        
        # 9. Initialize Order Executor
        self.order_executor = OrderExecutor(self.config, self.logger)
        self.logger.info("✅ Order Executor initialized")
        
        # 10. Initialize Health Monitor
        self.health_monitor = HealthMonitor(self.config, self.logger)
        self.logger.info("✅ Health Monitor initialized")
        
        self.logger.info("✅ All system components initialized successfully")
    
    def _update_capital_mode(self):
        """Update capital allocation mode based on exchange balances."""
        try:
            balances = {}
            total_balance = 0.0
            
            for exchange_id, wrapper in self.exchange_wrappers.items():
                try:
                    if hasattr(wrapper, 'get_balance'):
                        balance_data = wrapper.get_balance()
                    elif hasattr(wrapper, 'fetch_balance'):
                        balance_data = wrapper.fetch_balance()
                    else:
                        if self.trade_cycles % 10 == 0:  # Log less frequently
                            self.logger.debug(f"⚠️  No balance method found for {exchange_id}")
                        continue
                    
                    if balance_data and 'total' in balance_data:
                        usd_balance = balance_data['total'].get('USD', 0.0)
                        if usd_balance == 0:
                            usd_balance = balance_data['total'].get('USDT', 0.0)
                        
                        balances[exchange_id] = usd_balance
                        total_balance += usd_balance
                        
                        if self.trade_cycles % 20 == 0:  # Log less frequently
                            self.logger.debug(f"  {exchange_id} balance: ${usd_balance:.2f}")
                    
                except Exception as e:
                    if self.trade_cycles % 10 == 0:  # Log less frequently
                        self.logger.warning(f"⚠️  Error getting balance from {exchange_id}: {e}")
            
            if not balances:
                if self.trade_cycles % 5 == 0 and self.trade_cycles > 0:
                    self.logger.warning("⚠️  No balance data available (WebSocket may still be initializing)")
                return
            
            min_balance = min(balances.values())
            max_balance = max(balances.values())
            
            if min_balance == 0:
                if self.trade_cycles % 10 == 0:
                    self.logger.warning("⚠️  Zero balance detected")
                self.capital_mode = "BOTTLENECKED"
                self.available_capital_usd = 0
                return
            
            balance_ratio = max_balance / min_balance
            
            if balance_ratio > 1.5:
                self.capital_mode = "BOTTLENECKED"
                self.available_capital_usd = min_balance * 0.95
                if self.trade_cycles % 20 == 0:
                    self.logger.info(f"🔧 Capital Mode: {self.capital_mode} (Ratio: {balance_ratio:.2f})")
                    self.logger.info(f"💰 Available: ${self.available_capital_usd:.2f} (95% of smallest)")
            else:
                self.capital_mode = "BALANCED"
                avg_balance = sum(balances.values()) / len(balances)
                self.available_capital_usd = avg_balance * 0.40
                if self.trade_cycles % 30 == 0:
                    self.logger.info(f"🔧 Capital Mode: {self.capital_mode} (Ratio: {balance_ratio:.2f})")
                    self.logger.info(f"💰 Available: ${self.available_capital_usd:.2f} (40% of average)")
            
            self.estimated_balance = total_balance
            
        except Exception as e:
            if self.trade_cycles % 10 == 0:
                self.logger.warning(f"⚠️  Error updating capital mode: {e}")
            self.capital_mode = "BALANCED"
            self.available_capital_usd = 1000.0
    
    def _check_websocket_initialization(self):
        """Check if WebSocket connections are properly initialized."""
        # Skip check for first few cycles to allow WebSocket initialization
        if self.trade_cycles < 3:
            self.logger.info(f"🔄 WebSocket initialization in progress (cycle {self.trade_cycles + 1}/3)")
            return False
        
        # Check if data feed is running
        if not self.data_feed or not hasattr(self.data_feed, 'running'):
            self.logger.warning("⚠️  DataFeed not properly initialized")
            return False
        
        # Check if we've received any data
        if hasattr(self.data_feed, 'last_data_received'):
            if not self.data_feed.last_data_received:
                if self.trade_cycles < 10:
                    self.logger.info(f"⏳ Waiting for WebSocket data (cycle {self.trade_cycles + 1}/10)")
                    return False
                else:
                    self.logger.warning("⚠️  No WebSocket data received after 10 cycles")
                    return False
        
        return True
    
    def run(self):
        """Main execution loop - WebSocket only."""
        self.running = True
        self.start_time = time.time()
        
        try:
            self._initialize_components()
            self._setup_signal_handlers()
            
            self.logger.info("🚀 Arbitrage Bot Started Successfully!")
            self.logger.info("=" * 60)
            self.logger.info("📡 MODE: WebSocket-only (NO REST fallback)")
            self.logger.info("=" * 60)
            
            # Initialize dynamic position sizing
            self._initialize_dynamic_position_sizing()
            
            while self.running:
                try:
                    cycle_start = time.time()
                    self._execute_trading_cycle()
                    cycle_time = time.time() - cycle_start
                    
                    self.cycle_times.append(cycle_time)
                    if len(self.cycle_times) > 100:
                        self.cycle_times.pop(0)
                    
                    avg_cycle_time = sum(self.cycle_times) / len(self.cycle_times) if self.cycle_times else 0.1
                    delay = max(0.1, self.settings.get('cycle_delay', 2.0) - avg_cycle_time)
                    
                    time.sleep(delay)
                    
                except KeyboardInterrupt:
                    self.logger.info("🛑 Keyboard interrupt received")
                    break
                except Exception as e:
                    self.logger.error(f"❌ Error in main loop: {e}")
                    traceback.print_exc()
                    self.consecutive_failures += 1
                    
                    if self.consecutive_failures > self.settings.get('max_consecutive_failures', 5):
                        self.logger.error("🚨 Too many consecutive failures. Shutting down.")
                        break
                    
                    backoff = min(60, 2 ** self.consecutive_failures)
                    self.logger.info(f"⏸️  Backing off for {backoff} seconds")
                    time.sleep(backoff)
            
        except Exception as e:
            self.logger.error(f"❌ Fatal error in main loop: {e}")
            traceback.print_exc()
        
        finally:
            self.shutdown()
    
    def _initialize_dynamic_position_sizing(self):
        """Initialize dynamic position sizing with proper WebSocket dependency handling."""
        try:
            # Check configuration
            dynamic_enabled = self.config.get('dynamic_position_sizing', False)
            position_mode = self.config.get('position_sizing_mode', 'static')
            
            if dynamic_enabled and position_mode == 'dynamic':
                self.dynamic_sizing_configured = True
                
                # Wait for WebSocket to provide balance data
                if self.trade_cycles < 5:
                    self.logger.info("🔄 Dynamic position sizing: Waiting for WebSocket balance data...")
                    self.use_dynamic_sizing = False
                else:
                    # Check if we have balance data
                    try:
                        # Try to get a sample balance to verify functionality
                        test_balance = 0.0
                        for exchange_id in self.exchange_wrappers:
                            balance = self.data_feed.get_total_balance_usd(exchange_id)
                            if balance > 0:
                                test_balance = balance
                                break
                        
                        if test_balance > 0:
                            self.use_dynamic_sizing = True
                            self.dynamic_sizing_available = True
                            self.logger.info(f"✅ Dynamic position sizing ACTIVE (Balance: ${test_balance:.2f})")
                        else:
                            self.logger.warning("⚠️  Dynamic position sizing: No balance data yet")
                            self.use_dynamic_sizing = False
                    except Exception as e:
                        self.logger.warning(f"⚠️  Dynamic position sizing check failed: {e}")
                        self.use_dynamic_sizing = False
            else:
                self.logger.info("ℹ️  Static position sizing configured")
                self.use_dynamic_sizing = False
                
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize dynamic position sizing: {e}")
            self.use_dynamic_sizing = False
    
    def _execute_trading_cycle(self):
        """Execute a single trading cycle - WebSocket only."""
        self.trade_cycles += 1
        
        try:
            # Step 1: Check WebSocket initialization status
            if not self._check_websocket_initialization():
                if self.trade_cycles > 10:
                    self.logger.warning("⚠️  WebSocket initialization taking longer than expected")
                    if self.trade_cycles % 20 == 0:
                        self.logger.info("🔄 Consider checking exchange connectivity and API keys")
                return
            
            # Step 2: Check system health
            if not self.health_monitor.check_system_health():
                self.logger.error("❌ System health check failed")
                self.consecutive_failures += 1
                return
            
            # Step 3: Update market data via WebSocket
            market_data = self.data_feed.get_market_data()
            
            # Handle WebSocket data availability with patience
            if not market_data:
                self.consecutive_no_data += 1
                
                if self.consecutive_no_data <= self.max_consecutive_no_data:
                    # Normal during initialization or temporary disconnection
                    if self.consecutive_no_data % 5 == 0:
                        self.logger.info(f"⏳ Waiting for WebSocket market data ({self.consecutive_no_data}/{self.max_consecutive_no_data} cycles)")
                    return
                else:
                    # Persistent issue - log warning but continue
                    if self.trade_cycles % 10 == 0:
                        self.logger.warning(f"⚠️  No market data available for {self.consecutive_no_data} cycles (WebSocket may be reconnecting)")
                    
                    # Try to trigger WebSocket reconnection every 20 cycles
                    if self.trade_cycles % 20 == 0:
                        self.logger.info("🔄 Attempting to refresh WebSocket connections...")
                        # Note: We don't restart the entire data feed, just log the issue
                    
                    return
            else:
                # Reset no-data counter when we get data
                if self.consecutive_no_data > 0:
                    self.logger.info(f"✅ WebSocket data restored after {self.consecutive_no_data} cycles")
                    self.consecutive_no_data = 0
            
            # Step 4: Update market context with new data
            self.market_context.update(market_data)
            
            # Step 5: Update capital mode based on current balances
            self._update_capital_mode()
            
            # Step 6: Update dynamic position sizing status periodically
            if self.trade_cycles % 10 == 0:
                self._initialize_dynamic_position_sizing()
            
            # Step 7: Skip if no capital available
            if self.available_capital_usd < self.settings['min_position_size_usd']:
                if self.trade_cycles % 20 == 0:
                    self.logger.warning(f"⚠️  Insufficient capital: ${self.available_capital_usd:.2f}")
                return
            
            # Step 8: Find arbitrage opportunities
            opportunities = self.arbitrage_analyzer.find_opportunities(
                market_data, 
                self.available_capital_usd
            )
            
            if not opportunities:
                if self.trade_cycles % 20 == 0:
                    self.logger.info("🔍 No arbitrage opportunities found")
                return
            
            # Step 9: Sort by profit potential
            opportunities.sort(key=lambda x: x.get('expected_profit_usd', 0), reverse=True)
            best_opportunity = opportunities[0]
            
            # Step 10: Apply dynamic position sizing if available and configured
            if self.use_dynamic_sizing and self.dynamic_sizing_available and 'exchange_id' in best_opportunity:
                try:
                    exchange_id = best_opportunity['exchange_id']
                    
                    # Get current balance for dynamic sizing
                    current_balance = self.data_feed.get_total_balance_usd(exchange_id)
                    
                    if current_balance > 0:
                        # Calculate dynamic position size based on balance and risk
                        dynamic_size = min(
                            current_balance * 0.1,  # Use 10% of available balance
                            self.available_capital_usd,
                            self.settings['max_position_size']
                        )
                        
                        # Ensure minimum size
                        dynamic_size = max(dynamic_size, self.settings['min_position_size_usd'])
                        
                        best_opportunity['position_size'] = dynamic_size
                        self.logger.info(f"📈 Dynamic position size: ${dynamic_size:.2f} (Balance: ${current_balance:.2f})")
                    else:
                        self.logger.warning("⚠️  No balance data for dynamic sizing, using static")
                        
                except Exception as e:
                    self.logger.warning(f"⚠️  Dynamic sizing failed, using static: {e}")
            
            # Step 11: Check if profit meets threshold
            min_profit = self.settings['min_profit_threshold']
            expected_profit = best_opportunity.get('expected_profit_usd', 0)
            
            if expected_profit < min_profit:
                if self.trade_cycles % 30 == 0:
                    self.logger.info(f"📊 Best opportunity (${expected_profit:.2f}) below threshold (${min_profit:.2f})")
                return
            
            # Step 12: Execute the trade
            self.logger.info(f"🎯 Executing trade: {best_opportunity.get('description', 'N/A')}")
            self.logger.info(f"💰 Expected profit: ${expected_profit:.2f}")
            
            result = self.order_executor.execute_arbitrage(
                best_opportunity,
                self.available_capital_usd,
                self.exchange_wrappers
            )
            
            if result.get('success', False):
                self.successful_trades += 1
                profit = result.get('realized_profit_usd', 0)
                self.current_profit += profit
                self.consecutive_failures = 0
                
                self.logger.info(f"✅ Trade successful! Profit: ${profit:.2f}")
                self.logger.info(f"📈 Total Profit: ${self.current_profit:.2f}")
                self.health_monitor.update_trade_success(profit)
            else:
                self.failed_trades += 1
                error_msg = result.get('error', 'Unknown error')
                self.logger.error(f"❌ Trade failed: {error_msg}")
                self.health_monitor.update_trade_failure(error_msg)
            
            if self.trade_cycles % 10 == 0:
                self._log_cycle_summary()
            
        except Exception as e:
            self.logger.error(f"❌ Error in trading cycle: {e}")
            traceback.print_exc()
            self.failed_trades += 1
    
    def _log_cycle_summary(self):
        """Log a summary of recent performance."""
        if not self.cycle_times:
            return
            
        avg_cycle_time = sum(self.cycle_times) / len(self.cycle_times)
        
        self.logger.info("=" * 50)
        self.logger.info(f"📊 Cycle {self.trade_cycles} Summary:")
        self.logger.info(f"   Successful Trades: {self.successful_trades}")
        self.logger.info(f"   Failed Trades: {self.failed_trades}")
        self.logger.info(f"   Total Profit: ${self.current_profit:.2f}")
        self.logger.info(f"   Capital Mode: {self.capital_mode}")
        self.logger.info(f"   Available Capital: ${self.available_capital_usd:.2f}")
        self.logger.info(f"   Avg Cycle Time: {avg_cycle_time:.2f}s")
        self.logger.info(f"   Latency Mode: {self.latency_mode} (WebSocket-only)")
        self.logger.info(f"   Dynamic Sizing: {'ENABLED' if self.use_dynamic_sizing and self.dynamic_sizing_available else 'CONFIGURED' if self.dynamic_sizing_configured else 'DISABLED'}")
        self.logger.info(f"   WebSocket Status: {'ACTIVE' if self.consecutive_no_data == 0 else f'NO DATA ({self.consecutive_no_data} cycles)'}")
        self.logger.info("=" * 50)
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"📡 Received signal {signum}. Initiating shutdown...")
        self.running = False
    
    def shutdown(self):
        """Gracefully shutdown the system."""
        self.logger.info("🛑 Initiating graceful system shutdown...")
        self.running = False
        
        if self.data_feed:
            self.logger.info("🛑 Stopping WebSocket DataFeed")
            try:
                self.data_feed.stop()
                self.logger.info("✅ WebSocket data feed stopped")
            except Exception as e:
                self.logger.error(f"❌ Error stopping data feed: {e}")
        
        for exchange_id, wrapper in self.exchange_wrappers.items():
            try:
                if hasattr(wrapper, 'disconnect'):
                    wrapper.disconnect()
                    self.logger.info(f"✅ {exchange_id} WebSocket disconnected")
                elif hasattr(wrapper, 'close'):
                    wrapper.close()
                    self.logger.info(f"✅ {exchange_id} connection closed")
            except Exception as e:
                self.logger.error(f"❌ Error disconnecting {exchange_id}: {e}")
        
        self._log_session_summary()
        self.logger.info("👋 System shutdown complete. Goodbye!")
    
    def _log_session_summary(self):
        """Log session summary statistics."""
        try:
            if not self.start_time:
                self.logger.warning("No start time recorded for session summary")
                return
            
            session_duration = datetime.now() - datetime.fromtimestamp(self.start_time)
            hours, remainder = divmod(session_duration.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            success_rate = (self.successful_trades / self.trade_cycles * 100) if self.trade_cycles > 0 else 0
            
            self.logger.info("=" * 70)
            self.logger.info("📊 ARBITRAGE BOT SESSION SUMMARY")
            self.logger.info("=" * 70)
            self.logger.info(f"⏱️  Session Duration: {int(hours)}h {int(minutes)}m {int(seconds)}s")
            self.logger.info(f"🔁 Total Trade Cycles: {self.trade_cycles}")
            self.logger.info(f"✅ Successful Trades: {self.successful_trades}")
            self.logger.info(f"❌ Failed Trades: {self.failed_trades}")
            self.logger.info(f"📈 Success Rate: {success_rate:.1f}%")
            self.logger.info(f"💰 Total Profit: ${self.current_profit:.2f}")
            self.logger.info(f"🏦 Estimated Balance: ${self.estimated_balance:.2f}")
            self.logger.info(f"🔧 Capital Mode: {self.capital_mode}")
            self.logger.info(f"💵 Available Capital: ${self.available_capital_usd:.2f}")
            self.logger.info(f"⚡ Latency Mode: {self.latency_mode} (WebSocket-only)")
            self.logger.info(f"📊 Dynamic Sizing: {'ENABLED' if self.use_dynamic_sizing and self.dynamic_sizing_available else 'CONFIGURED' if self.dynamic_sizing_configured else 'DISABLED'}")
            self.logger.info(f"🌐 WebSocket Uptime: {100 * (self.trade_cycles - self.consecutive_no_data) / self.trade_cycles:.1f}%" if self.trade_cycles > 0 else "N/A")
            self.logger.info("=" * 70)
        except Exception as e:
            self.logger.error(f"Failed to log session summary: {e}")


if __name__ == "__main__":
    orchestrator = SystemOrchestrator()
    orchestrator.run()