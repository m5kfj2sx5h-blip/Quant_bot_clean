import logging
import requests
from decimal import Decimal
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class SentimentAnalyzer:
    """
    Derivatives Signal Intelligence (Phase 11).
    Uses Coinbase Advanced Futures to calculate Spot-Future Basis.
    Basis > 0 (Contango) = Bullish (Whales Longing).
    Basis < 0 (Backwardation) = Bearish (Whales Shorting).
    """
    def __init__(self, config=None):
        self.config = config or {}
        self.base_url = "https://api.coinbase.com/api/v3/brokerage"
        self.cache_ttl = 60 # 1 min
        self.last_update = 0
        self.last_basis = Decimal('0')
        self.sentiment = "NEUTRAL"

    def get_bitcoin_basis(self, spot_price: Decimal) -> Decimal:
        """
        Fetches BTC Future price and calculates Basis %.
        Returns: Basis % (e.g. 0.005 for 0.5% premium).
        """
        try:
            # 1. Fetch Active BTC Future (Simplistic: First BTC product found)
            url = f"{self.base_url}/market/products?product_type=FUTURE"
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                return Decimal('0')
                
            data = resp.json()
            btc_future = None
            
            # Simple heuristic: Find first product ID containing "BTC"
            # In production, we'd filter for nearest expiry or 'unexpired'.
            for p in data.get('products', []):
                pid = p['product_id']
                if 'BTC' in pid and p['status'] == 'online':
                    btc_future = pid
                    break
            
            if not btc_future:
                return Decimal('0')

            # 2. Get Future Price
            # Public ticker endpoint
            ticker_url = f"{self.base_url}/market/products/{btc_future}/ticker"
            t_resp = requests.get(ticker_url, timeout=5)
            if t_resp.status_code != 200:
                return Decimal('0')
                
            future_price = Decimal(str(t_resp.json().get('price', '0')))
            
            if future_price == 0 or spot_price == 0:
                return Decimal('0')
                
            # 3. Calculate Basis
            basis = (future_price - spot_price) / spot_price
            
            self.last_basis = basis
            self._update_sentiment_label(basis)
            return basis
            
        except Exception as e:
            logger.warning(f"Sentiment Analysis Failed: {e}")
            return Decimal('0')

    def _update_sentiment_label(self, basis):
        if basis > Decimal('0.005'): # > 0.5% Premium
            self.sentiment = "BULLISH"
        elif basis < Decimal('-0.001'): # Negative
            self.sentiment = "BEARISH"
        else:
            self.sentiment = "NEUTRAL"
        
        logger.info(f"🐋 Whale Sentiment: {self.sentiment} (Basis: {basis*100:.3f}%)")

    def get_signal_multiplier(self) -> Decimal:
        """
        Returns a Risk Multiplier based on sentiment.
        Bullish -> 1.0 (Full Size)
        Bearish -> 0.5 (Half Size)
        Neutral -> 0.8 (Standard)
        """
        if self.sentiment == "BULLISH":
            return Decimal('1.0')
        elif self.sentiment == "BEARISH":
            return Decimal('0.5')
        return Decimal('0.8')
