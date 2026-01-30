import threading
from collections import defaultdict, deque
from decimal import Decimal
import statistics
import time
from typing import Dict, Optional, Tuple, List
from utils.logger import get_logger

logger = get_logger(__name__)

class MarketData:
    """
    Thread-safe aggregator for rolling market data metrics.
    Tracks volatility, momentum, imbalance, and depth ratios.
    """
    def __init__(self, window_size: int = 60):
        self.window_size = window_size
        # Price history: symbol -> deque of (timestamp, mid_price)
        self.price_history = defaultdict(lambda: deque(maxlen=window_size))
        self.lock = threading.Lock()
        
        # Latest computed metrics cache
        self.metrics = defaultdict(dict)

    def update(self, symbol: str, book: Dict) -> None:
        """
        Updates the aggregator with a new order book state.
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            book: Raw book data (Dict, Nested Dict, or Object)
        """
        if not book: return

        # ROBUST PARSING (Copy-cat of Q.py logic)
        bids, asks = None, None
        if isinstance(book, dict):
            bids = book.get('bids')
            asks = book.get('asks')
            if not bids: # Kraken Nested
                 for k, v in book.items():
                     if isinstance(v, dict) and 'bids' in v:
                         bids = v.get('bids')
                         asks = v.get('asks')
                         break
        elif hasattr(book, 'pricebook'): # Coinbase Object
            bids = book.pricebook.bids
            asks = book.pricebook.asks

        if not bids or not asks or len(bids) == 0 or len(asks) == 0:
            return

        try:
            # Handle format of entries
            bid_0 = bids[0]
            ask_0 = asks[0]
            
            def get_price(entry):
                if isinstance(entry, (list, tuple)): return Decimal(str(entry[0]))
                if hasattr(entry, 'price'): return Decimal(str(entry.price))
                if isinstance(entry, dict): return Decimal(str(entry.get('price', 0)))
                return Decimal('0')

            best_bid = get_price(bid_0)
            best_ask = get_price(ask_0)

            mid_price = (best_bid + best_ask) / 2
            
            with self.lock:
                self.price_history[symbol].append((time.time(), mid_price))
                self._compute_metrics(symbol, book, mid_price)
                
        except Exception as e:
            logger.error(f"Error updating market data for {symbol}: {e}")

    def _compute_metrics(self, symbol: str, book: Dict, mid_price: Decimal) -> None:
        """Internal method to compute metrics under lock."""
        # 1. Volatility (StdDev of prices in window)
        prices_list = [p for _, p in self.price_history[symbol]]
        if len(prices_list) >= 10:
            volatility = statistics.stdev(prices_list)
        else:
            volatility = Decimal('0.0')

        # 2. Momentum (Price change from start of window)
        if len(prices_list) >= 2:
            start_price = prices_list[0]
            momentum = (mid_price - start_price) / start_price
        else:
            momentum = Decimal('0.0')

        # 3. Order Book Imbalance & Depth Ratio (at 5% depth)
        imbalance, depth_ratio = self._calculate_book_metrics(book, mid_price)

        self.metrics[symbol] = {
            'volatility': volatility,
            'momentum': momentum,
            'imbalance': imbalance,
            'depth_ratio': depth_ratio,
            'mid_price': mid_price,
            'timestamp': time.time()
        }

    def _calculate_book_metrics(self, book: Dict, mid_price: Decimal, depth_pct: float = 0.05) -> Tuple[Decimal, Decimal]:
        """Calculates imbalance."""
        # Need to re-extract because 'book' is raw. 
        # Optimization: Pass extracted bids/asks to this private method? 
        # For now, repeat extraction or rely on helper.
        
        bids, asks = None, None
        if isinstance(book, dict):
             bids = book.get('bids')
             if not bids:
                 for v in book.values():
                     if isinstance(v, dict) and 'bids' in v:
                         bids = v.get('bids')
                         asks = v.get('asks')
                         break
             else:
                 asks = book.get('asks')
        elif hasattr(book, 'pricebook'):
            bids = book.pricebook.bids
            asks = book.pricebook.asks
            
        if not bids: return Decimal('0'), Decimal('1.0')

        target_bid = mid_price * (Decimal('1') - Decimal(str(depth_pct)))
        target_ask = mid_price * (Decimal('1') + Decimal(str(depth_pct)))
        
        bid_vol = Decimal('0')
        ask_vol = Decimal('0')
        
        # Helper to extract p, q from entry
        def get_pq(entry):
            if isinstance(entry, (list, tuple)): return Decimal(str(entry[0])), Decimal(str(entry[1]))
            if hasattr(entry, 'price'): return Decimal(str(entry.price)), Decimal(str(entry.size))
            if isinstance(entry, dict):
                return Decimal(str(entry.get('price', 0))), Decimal(str(entry.get('amount', 0) or entry.get('qty', 0)))
            return Decimal('0'), Decimal('0')
            
        for entry in bids:
            price, qty = get_pq(entry)
            if price < target_bid: break
            bid_vol += qty
            
        for entry in asks:
            price, qty = get_pq(entry)
            if price > target_ask: break
            ask_vol += qty
            
        # Imbalance: (B - A) / (B + A)
        total_vol = bid_vol + ask_vol
        if total_vol > 0:
            imbalance = (bid_vol - ask_vol) / total_vol
        else:
            imbalance = Decimal('0')
            
        # Depth Ratio: B / A
        if ask_vol > 0:
            depth_ratio = bid_vol / ask_vol
        else:
            depth_ratio = Decimal('10.0') if bid_vol > 0 else Decimal('1.0') # Capped max if no asks
            
        return imbalance, depth_ratio

    def get_volatility(self, symbol: str) -> Decimal:
        return self.metrics.get(symbol, {}).get('volatility', Decimal('0.0'))

    def get_price_momentum(self, symbol: str) -> Decimal:
        return self.metrics.get(symbol, {}).get('momentum', Decimal('0.0'))

    def get_book_imbalance(self, symbol: str) -> Decimal:
        return self.metrics.get(symbol, {}).get('imbalance', Decimal('0.0'))

    def get_depth_ratio(self, symbol: str) -> Decimal:
        return self.metrics.get(symbol, {}).get('depth_ratio', Decimal('1.0'))

    def get_market_means(self) -> Dict[str, Decimal]:
        """Returns average metrics across all monitored symbols."""
        if not self.metrics:
            return {'imbalance_mean': Decimal('0'), 'depth_ratio_mean': Decimal('0')}
            
        imbalances = [m['imbalance'] for m in self.metrics.values()]
        ratios = [m['depth_ratio'] for m in self.metrics.values()]
        
        return {
            'imbalance_mean': statistics.mean(imbalances) if imbalances else Decimal('0'),
            'depth_ratio_mean': statistics.mean(ratios) if ratios else Decimal('0')
        }
