"""
Main orchestration - Q-Bot gets dedicated thread, never blocked
"""
import asyncio
import logging
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from system import SystemCoordinator
from bots.Q import QBot
from bots.A import ABot
from bots.G import GBot
from core.health_monitor import HealthMonitor

# Configure logging BEFORE anything else
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler('quant_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class QBotDedicatedThread:
    """Q-Bot runs in isolated thread with CPU affinity"""

    def __init__(self, q_bot: QBot):
        self.q_bot = q_bot
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="QBot")
        self.is_running = False

    def start(self):
        """Start Q-Bot in dedicated thread"""
        logger.critical("=== Q-BOT STARTING IN DEDICATED THREAD ===")
        self.is_running = True

        # Set CPU affinity if on Linux (optional but helps)
        try:
            import os
            os.system("taskset -p -c 1 %d" % os.getpid())
        except:
            pass

        self.executor.submit(self._run_qbot_loop)

    def _run_qbot_loop(self):
        """Q-Bot's isolated event loop - NOTHING interferes"""
        try:
            # Q-Bot gets its OWN event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Run Q-Bot's arbitrage cycle
            loop.run_until_complete(self.q_bot.run_arbitrage_cycle())

        except Exception as e:
            logger.critical(f"Q-BOT FATAL ERROR: {e}", exc_info=True)
            # Restart Q-Bot if it crashes
            if self.is_running:
                logger.critical("Restarting Q-Bot...")
                self._run_qbot_loop()

    def stop(self):
        self.is_running = False
        self.q_bot.stop()
        self.executor.shutdown(wait=True)


async def main():
    """Main entry point - orchestrates all bots"""
    logger.critical("=" * 60)
    logger.critical("QUANT_BOT 3.0 STARTING")
    logger.critical("=" * 60)

    # Initialize system coordinator
    system = SystemCoordinator()
    await system.initialize()

    # Create bots
    q_bot = QBot(system)
    a_bot = ABot(system)
    g_bot = GBot(system)

    # CRITICAL: Start Q-Bot in dedicated thread
    qbot_thread = QBotDedicatedThread(q_bot)
    qbot_thread.start()

    # Start health monitor (non-blocking)
    health_monitor = HealthMonitor(system.portfolio, system.alert_manager)
    asyncio.create_task(health_monitor.start())

    # Start A-Bot and G-Bot in main thread (they cooperate with Q-Bot)
    try:
        await asyncio.gather(
            a_bot.run(),
            g_bot.run(),
            system.dashboard.start(),
            return_exceptions=True
        )
    except KeyboardInterrupt:
        logger.critical("Shutdown signal received")

    # Cleanup
    qbot_thread.stop()
    await system.shutdown()

    logger.critical("QUANT_BOT 3.0 SHUTDOWN COMPLETE")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Main loop error: {e}", exc_info=True)
        sys.exit(1)
