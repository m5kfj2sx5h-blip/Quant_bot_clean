"""
Verification Test for GNN Extension (Step 3 Premium)
Tests GNN integration in ConversionManager and Q-Bot triangular scans.
"""
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch
import sys
import logging

# Mock dependencies
sys.modules['torch'] = MagicMock()
sys.modules['torch.nn'] = MagicMock()
sys.modules['torch.nn.functional'] = MagicMock()
sys.modules['torch_geometric'] = MagicMock()
sys.modules['torch_geometric.nn'] = MagicMock()
sys.modules['torch_geometric.data'] = MagicMock()
sys.modules['networkx'] = MagicMock()

# Mock Logger to avoid PermissionError
mock_logger = MagicMock()
sys.modules['utils.logger'] = MagicMock()
sys.modules['utils.logger'].get_logger = MagicMock(return_value=mock_logger)

# Configure logging to stdout only for test
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

# Import GNN Detector (which will mock internally if actual import fails)
from manager.gnn_detector import GNNArbitrageDetector

class TestGNNExtension(unittest.TestCase):
    def setUp(self):
        self.mock_gnn = MagicMock()
        # Ensure detect returns a valid list of cycles
        self.mock_gnn.detect.return_value = [
            {'path': ['USDT', 'BTC', 'ETH'], 'profit': 0.05, 'length': 3}
        ]
        
    def test_conversion_manager_integration(self):
        """Test that ConversionManager calls GNN when enabled."""
        
        # Patch the MODULE level flag where it is defined
        with patch('manager.gnn_detector.GNN_AVAILABLE', True):
            from manager.conversion import ConversionManager
            
            cm = ConversionManager(config={'USE_GNN': True})
            # Inject mock detector
            cm._gnn_detector = self.mock_gnn
            
            books = {'binance': {'BTC/USDT': {}, 'ETH/BTC': {}, 'ETH/USDT': {}}}
            
            # We expect it to try to run detection
            cm.detect_triangle(books)
            
            # Verify detect was called
            self.mock_gnn.detect.assert_called_once()
            print("[PASS] ConversionManager invoked GNN detector")
        
    def test_qbot_triangular_scan_integration(self):
        """Test that GNN Detector handles single-exchange input format correctly."""
        # Ensure GNN is available and torch is mocked
        with patch('manager.gnn_detector.GNN_AVAILABLE', True), \
             patch('manager.gnn_detector.torch', MagicMock()) as mock_torch:
            
            # Setup torch.no_grad context manager
            mock_torch.no_grad.return_value.__enter__.return_value = None
            
            detector = GNNArbitrageDetector()
            
            # Mock internal graph building and cycle detection dependencies
            # 1. Mock build_graph to return dummy data
            mock_data = MagicMock()
            mock_G = MagicMock()
            mock_rate_matrix = {}
            
            with patch.object(detector, 'build_graph', return_value=(mock_data, mock_G, mock_rate_matrix)):
                with patch.object(detector, '_create_model', return_value=MagicMock()):
                    # 2. Mock _prune_graph to return the graph as-is (bypass ML logic)
                    with patch.object(detector, '_prune_graph', return_value=mock_G):
                        # 3. Configure simple_cycles directly on the mocked module
                        # (patching string 'networkx.simple_cycles' is flaky with sys.modules mocks)
                        mock_nx = sys.modules['networkx']
                        mock_nx.simple_cycles.return_value = [[0, 1, 2]]
                        
                        # Setup asset mapping
                        detector.asset_to_idx = {'A':0, 'B':1, 'C':2}
                        detector.idx_to_asset = {0:'A', 1:'B', 2:'C'}
                        
                        # 4. Mock profit calculation
                        with patch.object(detector, '_calculate_cycle_profit', return_value=Decimal('0.05')):
                             
                             # Input: {exchange: {pair: book}}
                             books = {'kraken': {'BTC/USDT': {'bids':[[1,1]], 'asks':[[1,1]]}}}
                             
                             cycles = detector.detect(books)
                                 
                             print(f"[DEBUG] Cycles found: {cycles}")
                             
                             # Debug assertions
                             detector._prune_graph.assert_called()
                             # Debug assertions
                             detector._prune_graph.assert_called()
                             mock_nx.simple_cycles.assert_called()
                             detector._calculate_cycle_profit.assert_called()
                             
                             self.assertTrue(len(cycles) > 0, "No cycles detected")
                             self.assertEqual(cycles[0]['profit'], 0.05)
                             self.assertEqual(cycles[0]['path'], ['A', 'B', 'C'])
                             print("[PASS] GNN Detector handles single-exchange input format")

if __name__ == '__main__':
    unittest.main()
