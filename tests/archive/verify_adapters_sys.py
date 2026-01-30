import asyncio
import sys
import os
import logging
from decimal import Decimal

# Fix path
sys.path.append(os.getcwd())

from manager.data_feed import UnifiedDataFeed
from core.persistence import PersistenceManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VerifyAdapters")

async def verify_system():
    print("🧪 Verifying Exchange Adapters & Data Feed...")
    
    # 1. Initialize Feed (Auto-loads adapters)
    config = {'exchanges': {'binanceus':{}, 'kraken':{}, 'coinbase':{}}, 'paper_mode': True}
    feed = UnifiedDataFeed(config)
    await feed.start()
    await asyncio.sleep(5) # Wait for ws
    
    # 2. Check Order Books
    for ex_name, adapter in feed.exchanges.items():
        print(f"\n--- Checking {ex_name.upper()} ---")
        
        # A. Order Book
        # Use simple pair known to exist
        pair = 'BTC/USDT'
        if ex_name == 'coinbase': pair = 'BTC-USD' # Ticker format
        if ex_name == 'kraken': pair = 'BTC/USD'
        
        # Use Adapter directly just to check standardization
        try:
             book = adapter.get_order_book(pair)
             if book and 'bids' in book and 'asks' in book:
                 print(f"✅ Order Book ({pair}): OK (Bids: {len(book['bids'])}, Asks: {len(book['asks'])})")
                 # Check Data Type (List of Lists/Tuples)
                 if len(book['bids']) > 0:
                      sample = book['bids'][0]
                      # Expecting [price, amount] (list or tuple)
                      if isinstance(sample, (list, tuple)) and len(sample) >= 2:
                           print(f"   Structure: Valid {type(sample)}")
                      else:
                           print(f"❌ Structure: Invalid {type(sample)} - {sample}")
             else:
                 print(f"❌ Order Book ({pair}): Empty or Invalid Keys")
        except Exception as e:
             print(f"⚠️ Book Fetch Failed: {e}")

        # B. Balance (Mock check if paper, real if live keys)
        try:
            bal = adapter.get_balance()
            if isinstance(bal, dict):
                 print(f"✅ Balance: OK (Keys: {list(bal.keys())[:3]}...)")
            else:
                 print(f"❌ Balance: Invalid Type {type(bal)}")
        except Exception as e:
            print(f"⚠️ Balance Fetch Failed: {e}")

    await feed.stop()

if __name__ == "__main__":
    loop = asyncio.events.new_event_loop()
    loop.run_until_complete(verify_system())
