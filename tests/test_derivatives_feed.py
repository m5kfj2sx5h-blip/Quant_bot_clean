import requests
import os
from dotenv import load_dotenv

load_dotenv('config/.env')

def test_binance_funding():
    print("\n--- Testing Binance Types ---")
    # specific to global vs us. BinanceUS usually no perps.
    # We check public global API for market sentiment (Signal only, not trading)
    url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ Binance Global Funding (BTCUSDT): {data.get('lastFundingRate')} (Next Sync: {data.get('nextFundingTime')})")
            return True
        else:
            print(f"❌ Binance Global Error: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Binance Exception: {e}")
        return False

def test_kraken_funding():
    print("\n--- Testing Kraken Futures ---")
    # Kraken Futures public ticker
    url = "https://futures.kraken.com/derivatives/api/v3/tickers" # simplistic
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Find BTC perp
            for ticker in data.get('tickers', []):
                if 'PF_BTCUSD' in ticker.get('symbol', ''): # Kraken symbol format varies
                     print(f"✅ Kraken Futures Found: {ticker['symbol']} Price:{ticker.get('last')}")
                     # Funding rate might be in a different endpoint, checking generic connectivity first
                     return True
            print("⚠️ Kraken Futures: Connected but BTC perp not found in summary.")
            return True
        else:
             print(f"❌ Kraken Error: {resp.status_code}")
             return False
    except Exception as e:
        print(f"❌ Kraken Exception: {e}")
        return False

def test_coinbase_funding():
    print("\n--- Testing Coinbase Advanced (Public) ---")
    # Public Products Endpoint
    url = "https://api.coinbase.com/api/v3/brokerage/market/products?product_type=FUTURE"
    try:
        resp = requests.get(url, timeout=5)
        # Note: Coinbase API might require auth even for products, or return empty if no perps allowed in region?
        # Actually public market data often requires no auth.
        if resp.status_code == 200:
            data = resp.json()
            # Look for BTC-INT (International) or INT-BTC? OR standard futures
            products = data.get('products', [])
            print(f"ℹ️ Coinbase returned {len(products)} futures products.")
            if len(products) > 0:
                print(f"✅ Coinbase Futures Found: {products[0]['product_id']}")
                return True
            else:
                 print("⚠️ Coinbase: Connected but 0 Futures Types found (Region Restricted?).")
                 return False
        else:
            print(f"❌ Coinbase Error: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Coinbase Exception: {e}")
        return False

if __name__ == "__main__":
    print("🧪 STARTING DERIVATIVES DATA PROBE 🧪")
    b = test_binance_funding()
    k = test_kraken_funding()
    c = test_coinbase_funding()
    
    if b or k or c:
        print("\n✅ SUCCESS: At least one major derivatives feed is accessible for Sentiment Analysis.")
    else:
        print("\n❌ FAILURE: No derivatives feeds accessible.")
