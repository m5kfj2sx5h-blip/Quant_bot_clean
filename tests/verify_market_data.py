
import unittest
from decimal import Decimal
import sys
from unittest.mock import MagicMock

# Mock utils.logger
sys.modules['utils.logger'] = MagicMock()

from manager.market_data import MarketData

class TestMarketData(unittest.TestCase):
    def setUp(self):
        self.md = MarketData(window_size=10)
        self.symbol = 'BTC/USDT'

    def test_metrics_calculation(self):
        # 1. Feed mock data (Rising prices)
        # Price history: 100 -> 101 -> 102 ... -> 105
        # This should create positive momentum and non-zero volatility
        
        for i in range(10):
            price = Decimal(str(100 + i))
            book = {
                'bids': [[price - 1, 10]], # Price, Qty
                'asks': [[price + 1, 5]]
            }
            self.md.update(self.symbol, book)
            
        # Verify Metrics
        vol = self.md.get_volatility(self.symbol)
        mom = self.md.get_price_momentum(self.symbol)
        imba = self.md.get_book_imbalance(self.symbol)
        depth = self.md.get_depth_ratio(self.symbol)
        
        print(f"\n[DEBUG] Volatility: {vol}")
        print(f"[DEBUG] Momentum: {mom}")
        print(f"[DEBUG] Imbalance: {imba}")
        print(f"[DEBUG] Depth Ratio: {depth}")
        
        # 1. Volatility should be > 0
        self.assertTrue(vol > 0, "Volatility should be positive")
        
        # 2. Momentum should be positive (109 vs 100)
        # prices[0] was 100 (mid of 99 and 101) -> Wait, logic check
        # update 0: bid 99, ask 101 -> mid 100.
        # update 9: bid 108, ask 110 -> mid 109.
        # Momentum = (109 - 100) / 100 = 0.09
        self.assertTrue(mom > 0, "Momentum should be positive for rising trend")
        
        # 3. Imbalance
        # Bid Vol = 10, Ask Vol = 5
        # (10 - 5) / (10 + 5) = 5 / 15 = 0.333
        self.assertTrue(imba > 0, "Imbalance should be positive (More bids)")
        self.assertAlmostEqual(float(imba), 0.333, places=2)
        
        # 4. Depth Ratio
        # 10 / 5 = 2.0
        self.assertEqual(depth, Decimal('2.0'))
        
        print("[PASS] Market Data Metrics Verified")

if __name__ == '__main__':
    unittest.main()
