"""
Phase A2: Exchange Adapter Verification
Tests that each adapter returns standardized data structures.
"""
import sys
import os
import logging
from decimal import Decimal

sys.path.append(os.getcwd())

from dotenv import load_dotenv
load_dotenv('config/.env')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VerifyAdapters")

def test_binanceus():
    print("\n=== BINANCEUS ADAPTER ===")
    try:
        from adapters.exchanges.binanceus import BinanceUSAdapter
        adapter = BinanceUSAdapter()
        
        # 1. Order Book
        book = adapter.get_order_book('BTCUSDT')
        if book and 'bids' in book and 'asks' in book:
            print(f"✅ get_order_book: OK (Bids: {len(book.get('bids',[]))}, Asks: {len(book.get('asks',[]))})")
            if book['bids']:
                sample = book['bids'][0]
                print(f"   Sample Bid: {sample} (Type: {type(sample)})")
        else:
            print(f"❌ get_order_book: Missing keys or empty")
        
        # 2. Balance
        bal = adapter.get_balance()
        if isinstance(bal, dict):
            print(f"✅ get_balance: OK (Sample Keys: {list(bal.keys())[:3]})")
        else:
            print(f"❌ get_balance: Invalid type {type(bal)}")
            
        # 3. get_order (Mock - we don't have a real order ID)
        # Just check method exists
        if hasattr(adapter, 'get_order'):
            print(f"✅ get_order: Method Exists")
        else:
            print(f"❌ get_order: Method Missing!")
            
    except Exception as e:
        print(f"⚠️ BinanceUS Test Failed: {e}")

def test_kraken():
    print("\n=== KRAKEN ADAPTER ===")
    try:
        from adapters.exchanges.kraken import KrakenAdapter
        adapter = KrakenAdapter()
        
        book = adapter.get_order_book('XXBTZUSD') # Kraken symbol
        if book and 'bids' in book and 'asks' in book:
            print(f"✅ get_order_book: OK")
        else:
            print(f"❌ get_order_book: Missing keys")
        
        bal = adapter.get_balance()
        if isinstance(bal, dict):
            print(f"✅ get_balance: OK")
        else:
            print(f"❌ get_balance: Invalid type")
            
        if hasattr(adapter, 'get_order'):
            print(f"✅ get_order: Method Exists")
        else:
            print(f"❌ get_order: Method Missing!")
            
    except Exception as e:
        print(f"⚠️ Kraken Test Failed: {e}")

def test_coinbase():
    print("\n=== COINBASE ADAPTER ===")
    try:
        from adapters.exchanges.coinbase_adv import CoinbaseAdvancedAdapter
        adapter = CoinbaseAdvancedAdapter()
        
        book = adapter.get_order_book('BTC-USD')
        if book and 'bids' in book and 'asks' in book:
            print(f"✅ get_order_book: OK")
        else:
            print(f"❌ get_order_book: Missing keys")
        
        bal = adapter.get_balance()
        if isinstance(bal, dict):
            print(f"✅ get_balance: OK")
        else:
            print(f"❌ get_balance: Invalid type")
            
        if hasattr(adapter, 'get_order'):
            print(f"✅ get_order: Method Exists")
        else:
            print(f"❌ get_order: Method Missing!")
            
    except Exception as e:
        print(f"⚠️ Coinbase Test Failed: {e}")

if __name__ == "__main__":
    print("🧪 PHASE A2: Exchange Adapter Verification")
    test_binanceus()
    test_kraken()
    test_coinbase()
    print("\n✅ Adapter Verification Complete")
