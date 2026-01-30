
import sys
import os
import sqlite3
import json
from decimal import Decimal

# Add project root to path
sys.path.append(os.getcwd())

from adapters.persistence import PersistenceManager

def inspect_data():
    pm = PersistenceManager()
    state = pm.load_last_state()
    
    print("\n--- PERSISTENCE STATE DUMP ---")
    if not state:
        print("❌ No state found in DB!")
        return

    print(f"Total Value USD: {state.get('total_value_usd')} (Raw)")
    
    raw_balances = state.get('exchange_balances', '{}')
    print(f"\nExchange Balances (Raw JSON): {raw_balances}")
    
    try:
        balances = json.loads(raw_balances)
        for exchange, assets in balances.items():
            print(f"\nExchange: {exchange}")
            for asset, amount in assets.items():
                print(f"  - {asset}: {amount}")
    except Exception as e:
        print(f"❌ JSON Parse Error: {e}")

    print("\n--- MARKET SNAPSHOTS ---")
    snapshots = pm.get_market_snapshots()
    for s in snapshots:
        print(f"  {s['symbol']}: {s['bid']} / {s['ask']}")

if __name__ == "__main__":
    inspect_data()
