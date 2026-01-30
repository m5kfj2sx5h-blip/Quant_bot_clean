
import sqlite3
import json
import os

DB_PATH = "quant_bot.db"

def inspect_db():
    if not os.path.exists(DB_PATH):
        print(f"❌ DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n--- DB STATE ---")
    try:
        cursor.execute("SELECT key, value FROM kv_store")
        rows = cursor.fetchall()
        for key, value in rows:
            print(f"KEY: {key}")
            if key == 'exchange_balances':
                try:
                    data = json.loads(value)
                    print(json.dumps(data, indent=2))
                except:
                    print(value)
            else:
                print(value)
            print("-" * 20)
    except Exception as e:
        print(f"Error reading DB: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    inspect_db()
