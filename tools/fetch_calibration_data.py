
import json
import time
import urllib.request
import urllib.error
import ssl
from datetime import datetime
import pandas as pd
import os

# Bypass SSL verification
ssl._create_default_https_context = ssl._create_unverified_context

def fetch_binance_klines(symbol='BTC/USDT', interval='1h', limit=1000):
    """
    Fetch OHLCV from Binance public API.
    Docs: https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klinecandlestick-data
    """
    api_symbol = symbol.replace('/', '')
    base_url = "https://api.binance.us/api/v3/klines" # Using Binance.US as per config
    # Fallback to global if US fails
    
    print(f"Fetching {symbol} from Binance...")
    
    all_data = []
    end_time = int(time.time() * 1000)
    
    # Fetch 3 batches to get enough data
    for _ in range(3):
        url = f"{base_url}?symbol={api_symbol}&interval={interval}&limit={limit}&endTime={end_time}"
        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())
                if not data:
                    break
                
                # [Open time, Open, High, Low, Close, Volume, Close time, ...]
                batch = []
                for k in data:
                    batch.append({
                        'timestamp': k[0],
                        'open': float(k[1]),
                        'high': float(k[2]),
                        'low': float(k[3]),
                        'close': float(k[4]),
                        'volume': float(k[5])
                    })
                
                all_data = batch + all_data
                end_time = batch[0]['timestamp'] - 1
                time.sleep(0.5)
                
        except Exception as e:
            print(f"Error fetching from Binance: {e}")
            # Try global binance if US failed?
            if "binance.us" in base_url:
                print("Retrying with Binance Global...")
                base_url = "https://api.binance.com/api/v3/klines"
                continue
            break

    if not all_data:
        print("No data fetched.")
        return

    df = pd.DataFrame(all_data)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    filename = f"data/{symbol.replace('/','_')}_{interval}.csv"
    os.makedirs('data', exist_ok=True)
    df.to_csv(filename, index=False)
    print(f"Saved {len(df)} rows to {filename}")
    
    # Calculate stats
    df['returns'] = df['close'].pct_change()
    volatility = df['returns'].std() * (24**0.5) # Daily vol from hourly
    print(f"Estimated Daily Volatility (sigma): {volatility:.4f}")

if __name__ == "__main__":
    fetch_binance_klines('BTC/USDT')
