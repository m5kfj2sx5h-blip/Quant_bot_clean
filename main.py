import asyncio
import json
import logging
import os
import signal
import sys
import time
import traceback
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

load_dotenv('config/.env')

from adapters.data.feed import DataFeed
from manager.scanner import MarketContext, ArbitrageAnalyzer
from core.order_executor import OrderExecutor
from core.health_monitor import HealthMonitor
from bot.Q import QBot
from bot.A import ABot
from bot.G import GBot
from manager.fee import FeeManager
from manager.money import MoneyManager
from manager.mode import ModeManager
from manager.signals import SignalServer
from manager.staking import StakingManager
from manager.transfer import TransferManager
from manager.registry import MarketRegistry, RegistryWorker
from manager.persistence import PersistenceManager
from manager.risk import RiskManager
from utils.logger import get_logger

from domain.aggregates import Portfolio
from domain.entities import TradingMode

logger = get_logger(__name__)


class SystemCoordinator:
    def __init__(self):
        self.config = self._load_config()
        self.exchanges = {}
        self.data_feed = None
        self.fee_manager = None
        self.money_manager = None
        self.mode_manager = None
        self.signals_server = None
        self.staking_manager = None
        self.transfer_manager = None
        self.health_monitor = None
        self.risk_manager = None
        self.market_registry = MarketRegistry()
        self.persistence_manager = PersistenceManager()
        self.registry_worker = None
        self.portfolio = Portfolio()
        self.bots = {}
        self.running = True
        self.last_money_check = 0

    def _load_config(self) -> Dict[str, Any]:
        with open('config/settings.json', 'r') as f:
            return json.load(f)

    async def initialize(self):
        from adapters.exchanges.binanceus import BinanceUSAdapter
        from adapters.exchanges.kraken import KrakenAdapter
        from adapters.exchanges.coinbase_reg import CoinbaseRegularAdapter
        from adapters.exchanges.coinbase_adv import CoinbaseAdvancedAdapter

        # 1. Restore Portfolio & Mode state from SQLite
        last_state = self.persistence_manager.load_last_state()
        if last_state:
            self.portfolio.restore_from_dict(last_state)
            logger.info(f"📊 Portfolio restored: Profit=${self.portfolio.total_profit_usd:,.2f}, TPV Snapshot=${self.portfolio.snapshot_tpv_at_signal:,.2f}")

        # 2. Initialize Adapters
        self.exchanges = {
            'binanceus': BinanceUSAdapter(),
            'kraken': KrakenAdapter(),
            'coinbase': CoinbaseRegularAdapter(),
            'coinbase_advanced': CoinbaseAdvancedAdapter()
        }

        # 3. Initialize Feed & Registry
        self.data_feed = DataFeed(self.config, logger, self.market_registry)
        # Set up a fake exchange config if it's missing to allow data_feed to initialize enabled exchanges
        if 'exchanges' not in self.config:
            self.config['exchanges'] = {
                'binanceus': {'enabled': True},
                'kraken': {'enabled': True},
                'coinbase': {'enabled': True},
                'coinbase_advanced': {'enabled': True}
            }

        try:
            await self.data_feed.start_websocket_feed()
        except Exception as e:
            logger.error(f"Failed to start WebSocket feed: {e}. Continuing with restricted data.")

        # 4. Initialize Managers
        self.fee_manager = FeeManager(self.config, self.exchanges, self.market_registry)
        self.staking_manager = StakingManager(self.exchanges, self.config)
        self.transfer_manager = TransferManager(self.exchanges, 'USDT', True, self.market_registry)
        self.health_monitor = HealthMonitor(self.portfolio, self._handle_alert, self.config, logger, self.market_registry)
        self.risk_manager = RiskManager(self.portfolio, self.config)
        self.arbitrage_analyzer = ArbitrageAnalyzer(self.config, logger)

        # 5. Initialize Registry Worker
        self.registry_worker = RegistryWorker(self.market_registry, self.exchanges)
        asyncio.create_task(self.registry_worker.start())

        # 6. Finalize Mode & Money Managers
        self.mode_manager = ModeManager(self.portfolio, os.getenv('WEBHOOK_PASSPHRASE'))
        if last_state and last_state.get('current_mode'):
            try:
                self.mode_manager.current_mode = TradingMode(last_state['current_mode'])
                logger.info(f"💾 Restored Mode: {self.mode_manager.current_mode}")
            except Exception as e:
                logger.warning(f"Could not restore mode from persistence: {e}")

        self.money_manager = MoneyManager('config/settings.json', self.exchanges, self.staking_manager, self.signals_server, self.mode_manager, self.market_registry, self.portfolio)

        # Signal Server handles both Macro and Sniper (ABot) signals
        self.signals_server = SignalServer(
            macro_callback=self.handle_mode_change,
            abot_callback=self.handle_abot_signal
        )
        self.signals_server.start()

        # Initial bot check based on current mode
        await self.update_bot_states()

        # Link money manager to signals server if needed
        self.money_manager.signals_manager = self.signals_server

        logger.info("🚀 SYSTEM COORDINATOR Initialized")

    async def _handle_alert(self, level: str, message: str):
        """Standardized alert handler for HealthMonitor."""
        logger.warning(f"🔔 ALERT [{level}]: {message}")
        if self.persistence_manager:
            # We could store alerts in a dedicated table, for now just log
            pass

    async def handle_mode_change(self, mode_str: str):
        """Callback for SignalServer when a macro mode change is received."""
        logger.info(f"Processing mode change to {mode_str}")

        # Capture Snapshot TPV at the time of signal for dynamic scaling
        if self.portfolio:
            self.portfolio.snapshot_tpv_at_signal = self.portfolio.total_value_usd
            logger.info(f"Snapshot TPV at mode switch: ${self.portfolio.snapshot_tpv_at_signal:,.2f}")

        success = await self.mode_manager.handle_tradingview_signal({
            'mode': mode_str.lower() + '_mode',
            'confidence': 1.0,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        if success:
            self.persistence_manager.update_portfolio_state(self.portfolio, self.mode_manager.get_current_mode().value)
            await self.update_bot_states()

    def handle_abot_signal(self, action: str, coin: str, data: Dict):
        """Callback for SignalServer when an A-Bot (Sniper) signal is received."""
        if 'abot' in self.bots:
            self.bots['abot'].handle_signal(action, coin, data)
        else:
            logger.warning("A-Bot signal received but A-Bot is not active")

    async def update_bot_states(self):
        """Lazy load and start/stop bots based on the current mode."""
        current_mode = self.mode_manager.get_current_mode()
        logger.info(f"Updating bot states for mode: {current_mode}")

        # Q-Bot is always active in both modes (85% in BTC, 15% in GOLD)
        if 'qbot' not in self.bots:
            self.bots['qbot'] = QBot(
                self.config,
                self.exchanges,
                fee_manager=self.fee_manager,
                risk_manager=self.risk_manager,
                health_monitor=self.health_monitor,
                market_registry=self.market_registry,
                portfolio=self.portfolio,
                persistence_manager=self.persistence_manager,
                arbitrage_analyzer=self.arbitrage_analyzer,
                data_feed=self.data_feed
            )
            # Start Q-Bot loop if it has one

        # A-Bot: active only during BTC mode
        if current_mode == TradingMode.BTC_MODE:
            if 'abot' not in self.bots:
                logger.info("Initializing A-Bot (BTC Mode)")
                self.bots['abot'] = ABot(
                    self.config,
                    self.exchanges,
                    self.staking_manager,
                    self.fee_manager,
                    market_registry=self.market_registry,
                    portfolio=self.portfolio,
                    persistence_manager=self.persistence_manager
                )
        else:
            if 'abot' in self.bots:
                logger.info("Deactivating A-Bot (Leaving BTC Mode)")
                self.bots['abot'].liquidate_all()
                del self.bots['abot']

        # G-Bot: active only during GOLD mode
        if current_mode == TradingMode.GOLD_MODE:
            if 'gbot' not in self.bots:
                logger.info("Initializing G-Bot (GOLD Mode)")
                self.bots['gbot'] = GBot(
                    self.config,
                    self.exchanges,
                    self.fee_manager,
                    market_registry=self.market_registry,
                    portfolio=self.portfolio,
                    persistence_manager=self.persistence_manager
                )
        else:
            if 'gbot' in self.bots:
                logger.info("Deactivating G-Bot (Leaving GOLD Mode)")
                # G-Bot handles selling 85% on mode flip to BTC
                self.bots['gbot'].handle_mode_flip_to_btc()
                del self.bots['gbot']

    async def run(self):
        """Main execution loop for all active bots and monitors."""
        logger.info("🎬 Starting SYSTEM COORDINATOR Execution Loop")

        try:
            tasks = [
                self.health_monitor.start(),
                self._bot_loop()
            ]
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("System loop cancelled")
        except Exception as e:
            logger.critical(f"CRITICAL SYSTEM FAILURE: {e}", exc_info=True)
        finally:
            await self.shutdown()

    async def _bot_loop(self):
        """Infinite loop to trigger bot scans and money management."""
        while self.running:
            try:
                # 0. Check for Manual Commands from Dashboard
                if self.persistence_manager:
                    cmds = self.persistence_manager.get_pending_commands()
                    for cmd in cmds:
                        logger.info(f"Executing manual command: {cmd['command']}")
                        if cmd['command'] == 'SWITCH_MODE':
                            await self.handle_mode_change(cmd['params'].get('mode'))
                        elif cmd['command'] == 'G_SWEEP':
                            if 'gbot' in self.bots:
                                # Trigger sweep of 15% profits
                                self.bots['gbot'].execute_manual_sweep(self.portfolio.total_profit_usd)
                        self.persistence_manager.mark_command_complete(cmd['id'])

                # 1. Market Snapshots for Dashboard (Every Cycle)
                if self.persistence_manager and self.market_registry:
                    for ex in self.exchanges:
                        for sym in ['BTC/USDT', 'BTC/USD', 'PAXG/USDT', 'ETH/USDT']:
                            book = self.market_registry.get_order_book(ex, sym)
                            if book:
                                try:
                                    bid = Decimal(str(book.get('bid', book['bids'][0]['price'])))
                                    ask = Decimal(str(book.get('ask', book['asks'][0]['price'])))
                                    self.persistence_manager.save_market_snapshot(ex, sym, bid, ask)
                                except (KeyError, IndexError, ValueError):
                                    continue

                # 2. Money Management & Rebalancing (every 5 mins)
                if time.time() - self.last_money_check > 300:
                    try:
                        self.money_manager.generate_macro_plan(
                            price_data=self.data_feed.price_data,
                            min_btc_reserve=Decimal('0.01'),
                            min_stable_reserve=Decimal('500')
                        )
                        # Periodic persistence of portfolio state
                        if self.persistence_manager:
                            # Snapshot Portfolio
                            self.persistence_manager.update_portfolio_state(
                                self.portfolio,
                                self.mode_manager.get_current_mode().value
                            )
                        self.last_money_check = time.time()
                    except Exception as e:
                        logger.error(f"Money Manager error: {e}")

                # 2. Q-Bot Arbitrage Scans (Always active)
                if 'qbot' in self.bots:
                    # Fetch live balances for sizing
                    balances = {name: self.exchanges[name].get_balance('USDT') for name in self.exchanges}

                    # Cross-exchange scan
                    cross_opps = await self.bots['qbot'].scan_cross_exchange(balances)
                    for opp in sorted(cross_opps, key=lambda x: x['net_profit_pct'], reverse=True):
                        success = await self.bots['qbot'].execute_cross_exchange(opp)
                        if success: break  # Only one cross-ex per cycle to avoid double-spending same balance

                    # Triangular scan for each enabled exchange
                    for ex in self.exchanges:
                        tri_opps = await self.bots['qbot'].scan_triangular(ex, balances.get(ex, Decimal('0')))
                        if tri_opps:
                            # Execute best triangular opportunity for this exchange
                            best_tri = max(tri_opps, key=lambda x: x['net_profit_pct'])
                            await self.bots['qbot'].execute_triangular(best_tri)

                # 3. A-Bot Periodic Checks (BTC Mode)
                if 'abot' in self.bots:
                    self.bots['abot'].check_seat_warmers()
                    self.bots['abot'].stake_idle_funds()

                # 4. G-Bot Periodic Accumulation (GOLD Mode)
                if 'gbot' in self.bots:
                    # If in GOLD mode, ensure 85% of snapshot capital is in PAXG
                    paxg_price = Decimal('2500')  # Dynamic fallback
                    if self.market_registry:
                        for ex in self.exchanges:
                            book = self.market_registry.get_order_book(ex, 'PAXG/USDT')
                            if book:
                                paxg_price = Decimal(str(book.get('bid', book['bids'][0]['price'])))
                                break

                    total_paxg_value = sum(self.exchanges[ex].get_balance('PAXG') *
                                           paxg_price for ex in self.exchanges)

                    # Target is 85% of capital AT TIME OF SIGNAL
                    snapshot_tpv = self.portfolio.snapshot_tpv_at_signal if self.portfolio.snapshot_tpv_at_signal > 0 else self.portfolio.total_value_usd
                    target_gold = snapshot_tpv * Decimal('0.85')

                    if total_paxg_value < target_gold:
                        diff = target_gold - total_paxg_value
                        if diff > Decimal('100'):  # Minimum buy
                            self.bots['gbot'].accumulate_paxg(diff)

                await asyncio.sleep(self.config.get('cycle_times', {}).get('main_loop_sec', 10))
            except Exception as e:
                logger.error(f"Error in main bot loop: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def shutdown(self):
        self.running = False
        logger.info("🛑 Shutting down system...")
        if self.signals_server:
            self.signals_server.stop()
        if self.health_monitor:
            self.health_monitor.stop()
        if self.data_feed:
            self.data_feed.running = False


async def main():
    coord = SystemCoordinator()
    await coord.initialize()
    await coord.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass