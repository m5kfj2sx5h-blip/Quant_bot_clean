
import unittest
from unittest.mock import MagicMock
import sys
from decimal import Decimal

# Mock dependencies
sys.modules['binance.spot'] = MagicMock()
sys.modules['kraken.spot'] = MagicMock()
sys.modules['coinbase.rest'] = MagicMock()
sys.modules['domain.entities'] = MagicMock()
sys.modules['domain.values'] = MagicMock()
sys.modules['dotenv'] = MagicMock()

from adapters.exchanges.binanceus import BinanceUSAdapter
from adapters.exchanges.kraken import KrakenAdapter
from adapters.exchanges.coinbase_adv import CoinbaseAdvancedAdapter

class TestRawAdapters(unittest.TestCase):
    def test_binance_raw(self):
        adapter = BinanceUSAdapter()
        # Mock depth response: Raw API format
        raw_depth = {'bids': [['100.0', '1.0']], 'asks': [['101.0', '2.0']]}
        adapter.client.depth.return_value = raw_depth
        
        book = adapter.get_order_book("BTC/USDT")
        
        # Assert NO conversion happened
        self.assertEqual(book, raw_depth)
        self.assertIsInstance(book['bids'][0], list) 
        self.assertEqual(book['bids'][0][0], '100.0') # String, not Decimal
        print("\n[PASS] BinanceUS returns raw list of strings")

    def test_kraken_raw(self):
        adapter = KrakenAdapter()
        # Mock order book response: Raw API format
        # Suppose MarketClient returns whatever SDK returns. 
        # If SDK returns {'XXBT': {'bids': ...}}
        raw_book = {'XXBT': {'bids': [['200.0', '1.0', 123]], 'asks': [['201.0', '2.0', 123]]}}
        adapter.market_client.get_order_book.return_value = raw_book
        
        book = adapter.get_order_book("BTC/USD")
        
        self.assertEqual(book, raw_book)
        self.assertIsInstance(book['XXBT']['bids'][0], list)
        print("[PASS] Kraken returns raw nested dict")

    def test_coinbase_raw(self):
        adapter = CoinbaseAdvancedAdapter()
        # Mock Object response
        mock_obj = MagicMock()
        mock_bid = MagicMock()
        mock_bid.price = '300.0'
        mock_bid.size = '1.0'
        mock_obj.pricebook.bids = [mock_bid]
        mock_obj.pricebook.asks = []
        
        adapter.client.get_product_book.return_value = mock_obj
        
        book = adapter.get_order_book("BTC-USD")
        
        self.assertEqual(book, mock_obj)
        self.assertEqual(book.pricebook.bids[0].price, '300.0')
        print("[PASS] Coinbase returns raw object")

if __name__ == '__main__':
    unittest.main()
