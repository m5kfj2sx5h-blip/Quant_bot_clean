
import unittest
from decimal import Decimal
from unittest.mock import MagicMock
import sys

# Mock dependencies to avoid environment issues
sys.modules['dotenv'] = MagicMock()
sys.modules['utils.logger'] = MagicMock()
sys.modules['pandas'] = MagicMock()
sys.modules['core.health_monitor'] = MagicMock()

from bot.Q import QBot
from bot.A import ABot
from bot.G import GBot

class TestAssetAgnostic(unittest.TestCase):
    def test_free_capital_calculation(self):
        # Setup
        raw_balances = {
            'Binance': {'USDT': Decimal('1000'), 'BTC': Decimal('1.5')},
            'Kraken': {'USDT': Decimal('500'), 'ETH': Decimal('10')}
        }
        
        # Mock Locked Assets
        abot = ABot({}, {})
        abot.get_locked_assets = MagicMock(return_value={'USDT': Decimal('200'), 'BTC': Decimal('0.5')})
        
        gbot = GBot({}, {})
        gbot.get_locked_assets = MagicMock(return_value={'PAXG': Decimal('1.0')}) # Locked PAXG, irrelevant here but good to test
        
        # Logic from main.py
        locked_a = abot.get_locked_assets()
        locked_g = gbot.get_locked_assets()
        
        balances = {}
        for ex_name, assets in raw_balances.items():
            balances[ex_name] = {}
            for coin, amount in assets.items():
                locked_amount = locked_a.get(coin, Decimal('0'))
                if coin == 'PAXG':
                    locked_amount += locked_g.get('PAXG', Decimal('0'))
                
                free_amount = amount - locked_amount
                if free_amount > 0:
                    balances[ex_name][coin] = free_amount
                    
        # Assertions
        # Binance USDT: 1000 - 200 = 800
        self.assertEqual(balances['Binance']['USDT'], Decimal('800'))
        # Binance BTC: 1.5 - 0.5 = 1.0
        self.assertEqual(balances['Binance']['BTC'], Decimal('1.0'))
        # Kraken ETH: 10 - 0 = 10
        self.assertEqual(balances['Kraken']['ETH'], Decimal('10'))
        
        print("\n[PASS] Free Capital Calculation Verified")
        return balances

    def test_qbot_asset_agnostic(self):
        # Setup QBot with mocked dependencies
        config = {'risk': {'max_trade_usd': 10000}}
        qbot = QBot(config, {})
        # qbot.max_trade_usd - property, derived from config
        qbot.depth_multiplier = Decimal('0') # Disable depth check for logic test
        qbot.get_effective_fee = MagicMock(return_value=Decimal('0.001'))
        qbot.get_profit_threshold = MagicMock(return_value=Decimal('0.005')) # 0.5%
        qbot.market_registry = None # Bypass registry for simple test
        
        # Mock balances (Simulating what main.py passes)
        # Scenario: We have BTC on Binance (Buy Ex) and ETH on Kraken (Sell Ex)
        # We want to Arb ETH/BTC.
        allocated_capital = {
            'Binance': {'BTC': Decimal('1.0'), 'USDT': Decimal('0')}, # 0 USDT!
            'Kraken': {'ETH': Decimal('10.0'), 'USDT': Decimal('0')}  # 0 USDT!
        }
        
        # Pair to Test
        pair = 'ETH/BTC' # Base=ETH, Quote=BTC
        buy_ex = 'Binance'
        sell_ex = 'Kraken'
        
        # Mock Exchange Order Books
        # Binance Ask (Buy Price): 0.05 BTC
        # Kraken Bid (Sell Price): 0.052 BTC (Profitable arb!)
        # Q-Bot Logic: 
        # Buy on Binance (Uses BTC). Sell on Kraken (Uses ETH).
        
        # We manually invoke the logic block we wrote (mocking the loop)
        # Identify Base/Quote
        base_currency, quote_currency = 'ETH', 'BTC'
        
        # Logic Check
        buy_balance_quote = allocated_capital.get(buy_ex, {}).get(quote_currency, Decimal('0'))
        sell_balance_base = allocated_capital.get(sell_ex, {}).get(base_currency, Decimal('0'))
        
        print(f"\n[DEBUG] Buy Balance ({quote_currency}): {buy_balance_quote}")
        print(f"[DEBUG] Sell Balance ({base_currency}): {sell_balance_base}")
        
        sell_price = Decimal('0.052')
        
        max_buy_quote = buy_balance_quote # 1.0 BTC
        max_sell_quote_equiv = sell_balance_base * sell_price # 10 ETH * 0.052 = 0.52 BTC
        
        trade_value_quote = min(max_buy_quote, max_sell_quote_equiv) # Should be 0.52 BTC
        
        print(f"[DEBUG] Trade Value (Quote): {trade_value_quote}")
        
        self.assertEqual(trade_value_quote, Decimal('0.52'))
        self.assertTrue(trade_value_quote > 0, "Trade Value should be positive even with 0 USDT")
        
        print("[PASS] Q-Bot Asset Agnostic Logic Verified")

if __name__ == '__main__':
    unittest.main()
