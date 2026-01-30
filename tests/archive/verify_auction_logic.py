import unittest
from decimal import Decimal
import sys
import os

sys.path.append(os.getcwd())
from core.auction import AuctionContextModule, AuctionState, MarketContext

class TestAuctionLogic(unittest.TestCase):
    def setUp(self):
        self.module = AuctionContextModule()

    def test_imbalanced_selling(self):
        # Heavy Sell Wall, Thin Buy Support
        # Bids: 1 BTC @ 100
        # Asks: 50 BTC @ 101
        
        bids = [[100, 1]]
        asks = [[101, 50]]
        
        ctx = MarketContext('BTC-USDT')
        ctx = self.module.analyze_order_book(bids, asks, Decimal('100.5'), ctx)
        
        print(f"Detected State: {ctx.auction_state}, Score: {ctx.auction_imbalance_score}")
        
        # Should be IMBALANCED_SELLING (High supply, low demand)
        self.assertEqual(ctx.auction_state, AuctionState.IMBALANCED_SELLING)
        self.assertLess(ctx.auction_imbalance_score, -0.5)

    def test_balanced_book(self):
        bids = [[100, 10]]
        asks = [[101, 10]]
        
        ctx = MarketContext('BTC-USDT')
        ctx = self.module.analyze_order_book(bids, asks, Decimal('100.5'), ctx)
        
        self.assertEqual(ctx.auction_state, AuctionState.BALANCED)

if __name__ == '__main__':
    print("🧪 Verifying Auction Logic...")
    unittest.main()
