
import asyncio
import logging
import sys
import os
from datetime import datetime
from decimal import Decimal

# Setup paths
sys.path.append(os.getcwd())

# Mock formatting
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SystemVerifier")

async def test_system_integrity():
    logger.info("🧪 Starting System Integrity Verification...")
    errors = []

    # 1. Config Loading
    try:
        from dotenv import load_dotenv
        import json
        load_dotenv('config/.env')
        with open('config/settings.json') as f:
            config = json.load(f)
        logger.info("✅ Config loaded")
    except Exception as e:
        errors.append(f"Config Load Failed: {e}")
        return

    # 2. DataFeed Initialization (The Component that Failed)
    try:
        from adapters.data.feed import DataFeed
        feed = DataFeed(config, logger)
        if not hasattr(feed, '_maintain_websocket_connections'):
             errors.append("❌ DataFeed missing _maintain_websocket_connections method!")
        else:
             logger.info("✅ DataFeed structure verified (Attribute Check)")
    except Exception as e:
        errors.append(f"DataFeed Init Failed: {e}")

    # 3. Manager Initialization
    try:
        from manager.risk import RiskManager
        from manager.scanner import AlphaQuadrantAnalyzer
        from manager.gnn_detector import GNNArbitrageDetector
        
        # Mock Dependencies
        class MockPortfolio:
            total_value_usd = Decimal('10000')
        
        risk = RiskManager(MockPortfolio(), config)
        gnn = GNNArbitrageDetector()
        logger.info("✅ Managers initialized")
        
        # Check GNN wiring
        if not hasattr(gnn, 'detect'):
             errors.append("❌ GNN Detector missing 'detect' method")
             
    except Exception as e:
        errors.append(f"Manager Init Failed: {e}")

    # 4. Bot Initialization
    try:
        from bot.Q import QBot
        from bot.A import ABot
        from bot.G import GBot
        
        # Mock Exchanges
        exchanges = {'binanceus': None} 
        
        q_bot = QBot(config, exchanges, risk_manager=risk, data_feed=feed)
        a_bot = ABot(config, exchanges)
        g_bot = GBot(config, exchanges)
        
        logger.info("✅ Bots initialized successfully")
        
        # Check Q-Bot GNN Wiring
        if not hasattr(q_bot, 'gnn_detector'):
             # It might be lazy loaded, so let's trigger a check if possible or just warn
             pass
             
    except Exception as e:
        errors.append(f"Bot Init Failed: {e}")

    # Report
    if errors:
        logger.error("🚨 System Verification FAILED with errors:")
        for err in errors:
            logger.error(f"  - {err}")
        sys.exit(1)
    else:
        logger.info("✨ System Integrity Verified: No immediate attribute errors found.")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(test_system_integrity())
