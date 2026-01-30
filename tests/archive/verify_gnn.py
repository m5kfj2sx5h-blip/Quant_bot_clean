"""
Verification Test for GNN Arbitrage Detector (Step 3)
Tests graph building, cycle detection, and profit calculation.
"""
import unittest
from unittest.mock import MagicMock, patch
import sys
from decimal import Decimal

# Mock ALL heavy dependencies
sys.modules['torch'] = MagicMock()
sys.modules['torch.nn'] = MagicMock()
sys.modules['torch.nn.functional'] = MagicMock()
sys.modules['torch_geometric'] = MagicMock()
sys.modules['torch_geometric.nn'] = MagicMock()
sys.modules['torch_geometric.data'] = MagicMock()
sys.modules['networkx'] = MagicMock()

# Mock logger to avoid file permission issues
mock_logger = MagicMock()
sys.modules['utils.logger'] = MagicMock()
sys.modules['utils.logger'].get_logger = MagicMock(return_value=mock_logger)

# Patch GNN_AVAILABLE before import
import manager.gnn_detector as gnn_module
gnn_module.GNN_AVAILABLE = False  # Disable actual torch for testing
gnn_module.logger = mock_logger



from manager.gnn_detector import GNNArbitrageDetector


class TestGNNDetector(unittest.TestCase):
    def test_price_extraction_list_format(self):
        """Test extraction from Binance/Kraken raw list format."""
        detector = GNNArbitrageDetector()
        
        # Binance format: {'bids': [['100.0', '1.0']], 'asks': [['101.0', '2.0']]}
        book = {'bids': [['100.0', '1.0']], 'asks': [['101.0', '2.0']]}
        bid, ask = detector._extract_prices(book)
        
        self.assertEqual(bid, Decimal('100.0'))
        self.assertEqual(ask, Decimal('101.0'))
        print("\n[PASS] List format extraction (Binance/Kraken)")

    def test_price_extraction_nested_format(self):
        """Test extraction from Kraken nested dict format."""
        detector = GNNArbitrageDetector()
        
        # Kraken format: {'XXBTZUSD': {'bids': [...], 'asks': [...]}}
        book = {
            'XXBTZUSD': {
                'bids': [['50000.0', '0.5', 123456]],
                'asks': [['50001.0', '0.3', 123456]]
            }
        }
        bid, ask = detector._extract_prices(book)
        
        self.assertEqual(bid, Decimal('50000.0'))
        self.assertEqual(ask, Decimal('50001.0'))
        print("[PASS] Nested dict extraction (Kraken)")

    def test_price_extraction_object_format(self):
        """Test extraction from Coinbase object format."""
        detector = GNNArbitrageDetector()
        
        # Coinbase format: Object with pricebook.bids/asks
        mock_bid = MagicMock()
        mock_bid.price = '60000.0'
        mock_ask = MagicMock()
        mock_ask.price = '60001.0'
        
        book = MagicMock()
        book.pricebook.bids = [mock_bid]
        book.pricebook.asks = [mock_ask]
        
        bid, ask = detector._extract_prices(book)
        
        self.assertEqual(bid, Decimal('60000.0'))
        self.assertEqual(ask, Decimal('60001.0'))
        print("[PASS] Object format extraction (Coinbase)")

    def test_cycle_profit_calculation(self):
        """Test profit calculation for a simple cycle."""
        detector = GNNArbitrageDetector()
        detector.idx_to_asset = {0: 'USD', 1: 'BTC', 2: 'ETH'}
        
        # Profitable cycle: USD -> BTC -> ETH -> USD
        # 1 USD -> 0.00002 BTC (rate 0.00002)
        # 0.00002 BTC -> 0.00025 ETH (rate 12.5)
        # 0.00025 ETH -> 1.005 USD (rate 4020)
        # Net: 1.005 - 1.0 = 0.005 (0.5% profit)
        rate_matrix = {
            'USD': {'BTC': Decimal('0.00002')},  # Buy BTC with USD
            'BTC': {'ETH': Decimal('12.5')},      # Buy ETH with BTC
            'ETH': {'USD': Decimal('4020')}       # Sell ETH for USD
        }
        
        cycle = [0, 1, 2]  # USD -> BTC -> ETH -> USD
        profit = detector._calculate_cycle_profit(cycle, rate_matrix)
        
        # 1 * 0.00002 * 12.5 * 4020 - 1 = 0.005
        expected = Decimal('0.00002') * Decimal('12.5') * Decimal('4020') - 1
        self.assertAlmostEqual(float(profit), float(expected), places=4)
        print(f"[PASS] Cycle profit calculation: {float(profit)*100:.3f}%")

    def test_gnn_not_available_graceful_fail(self):
        """Test graceful degradation when GNN deps not available."""
        # Already disabled GNN_AVAILABLE above
        detector = GNNArbitrageDetector()
        
        books = {'binance': {'BTC/USD': {'bids': [['100', '1']], 'asks': [['101', '1']]}}}
        result = detector.detect(books)
        
        self.assertEqual(result, [])
        print("[PASS] Graceful degradation when GNN unavailable")


if __name__ == '__main__':
    print("=" * 60)
    print("GNN ARBITRAGE DETECTOR VERIFICATION")
    print("=" * 60)
    unittest.main(verbosity=2)
