
import unittest
from unittest.mock import MagicMock
from decimal import Decimal
import logging
# Fix import path
import sys
import os
sys.path.append(os.getcwd())

from manager.scanner import AlphaQuadrantAnalyzer

class TestAlphaQuadrant(unittest.TestCase):
    def setUp(self):
        self.mock_aggregator = MagicMock()
        self.config = {'ALPHA_THRESHOLD': 1.0, 'paper_mode': True}
        self.analyzer = AlphaQuadrantAnalyzer(self.mock_aggregator, config=self.config)
        
        # Silence logger
        logging.getLogger('manager.scanner').setLevel(logging.CRITICAL)

    def test_quadrant_scoring_top_right(self):
        """Test a perfect Top-Right Quadrant candidate."""
        # Setup mock returns
        # x (depth_ratio) = 2.0 (High Liquidity)
        # y (imbalance) = 0.5 (Strong Buy Pressure)
        # momentum = 0.1 (Positive)
        self.mock_aggregator.get_market_means.return_value = {
            'depth_ratio_mean': Decimal('1.0'), 
            'imbalance_mean': Decimal('0.0')
        }
        self.mock_aggregator.get_depth_ratio.return_value = Decimal('2.0')
        self.mock_aggregator.get_book_imbalance.return_value = Decimal('0.5')
        self.mock_aggregator.get_price_momentum.return_value = Decimal('0.1')
        
        # Expected score: y * x * (1 + |mom|) = 0.5 * 2.0 * (1 + 0.1) = 1.0 * 1.1 = 1.1
        results = self.analyzer.scan(['BTC/USDT'])
        
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]['score'], 1.1)
        self.assertEqual(results[0]['symbol'], 'BTC/USDT')
        print(f"[PASS] Top-Right Candidate Scored: {results[0]['score']}")

    def test_quadrant_filtering_bottom_left(self):
        """Test that Bottom-Left candidates (low depth, sell pressure) are filtered."""
        self.mock_aggregator.get_market_means.return_value = {
            'depth_ratio_mean': Decimal('1.0'), 
            'imbalance_mean': Decimal('0.0')
        }
        # x = 0.5 (Low Depth) < Mean (1.0)
        # y = -0.2 (Sell Pressure) < Mean (0.0)
        self.mock_aggregator.get_depth_ratio.return_value = Decimal('0.5')
        self.mock_aggregator.get_book_imbalance.return_value = Decimal('-0.2')
        self.mock_aggregator.get_price_momentum.return_value = Decimal('0.0')
        
        results = self.analyzer.scan(['ETH/USDT'])
        
        # Should be filtered out (score 0 or empty)
        self.assertEqual(len(results), 0)
        print("[PASS] Bottom-Left Candidate Filtered")

    def test_execution_logic_paper(self):
        """Test execution logic in paper mode."""
        res = self.analyzer.execute_alpha_snipe('BTC/USDT', Decimal('1.5'), Decimal('1000'))
        
        self.assertIsNotNone(res)
        self.assertEqual(res['status'], 'paper_executed')
        self.assertEqual(res['amount'], 150.0) # 15% of 1000
        print(f"[PASS] Paper Execution Amount: {res['amount']}")

    def test_execution_min_size_block(self):
        """Test execution blocked for small capital."""
        res = self.analyzer.execute_alpha_snipe('BTC/USDT', Decimal('1.5'), Decimal('50'))
        # 15% of 50 is 7.5, which is < 10 min size
        self.assertIsNone(res)
        print("[PASS] Small Snipe Blocked")

if __name__ == '__main__':
    unittest.main()
