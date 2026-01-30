
import sqlite3
import json
import os

DB_PATH = "logs/quant_bot.db"

def inspect_db():
    if not os.path.exists(DB_PATH):
        print(f"❌ DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"\n--- DB STATE ({DB_PATH}) ---")
    try:
        # Check table capability
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables: {tables}")
        
        # Check portfolio_state
        cursor.execute("SELECT * FROM portfolio_state ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            # Get column names
            cols = [description[0] for description in cursor.description]
            data = dict(zip(cols, row))
            print(f"\n--- LATEST STATE ---")
            print(f"Total Value: {data.get('total_value_usd')}")
            print(f"Exchange Balances: {data.get('exchange_balances')}")
        else:
            print("No portfolio state found.")
    except Exception as e:
        print(f"Error reading DB: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    inspect_db()
