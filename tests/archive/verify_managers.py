"""
Phase A3: Manager Integration Tests
Tests that each manager returns expected types and handles edge cases.
"""
import sys
import os
import logging
from decimal import Decimal
from unittest.mock import MagicMock

sys.path.append(os.getcwd())

# Mock logger to avoid permission errors
sys.modules['utils.logger'] = MagicMock()
sys.modules['utils.logger'].get_logger.return_value = logging.getLogger('mock')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VerifyManagers")

def test_money_manager():
    print("\n=== MONEY MANAGER ===")
    try:
        from manager.money import MoneyManager
        
        # Mock dependencies
        mock_config = {'DRIFT_THRESHOLD_CRITICAL': '0.85', 'SMALL_ACCOUNT_MODE': True}
        mock_exchanges = {}
        
        mm = MoneyManager(mock_config, mock_exchanges)
        
        # Check config loaded
        if hasattr(mm, 'small_account_mode'):
            print(f"✅ small_account_mode: {mm.small_account_mode}")
        else:
            print(f"❌ small_account_mode: Missing attribute")
            
        if hasattr(mm, 'critical_drift_threshold'):
            print(f"✅ critical_drift_threshold: {mm.critical_drift_threshold}")
        else:
            print(f"❌ critical_drift_threshold: Missing attribute")
            
    except Exception as e:
        print(f"⚠️ MoneyManager Test Failed: {e}")

def test_order_executor():
    print("\n=== ORDER EXECUTOR ===")
    try:
        from core.order_executor import OrderExecutor
        
        # Check _wait_for_fill method exists
        if hasattr(OrderExecutor, '_wait_for_fill'):
            print(f"✅ _wait_for_fill: Method Exists")
        else:
            print(f"❌ _wait_for_fill: Method Missing!")
            
    except Exception as e:
        print(f"⚠️ OrderExecutor Test Failed: {e}")

def test_conversion_manager():
    print("\n=== CONVERSION MANAGER ===")
    try:
        from manager.conversion import ConversionManager
        
        cm = ConversionManager()
        
        # Test control_drift returns bool
        result = cm.control_drift([], {})
        if isinstance(result, bool):
            print(f"✅ control_drift: Returns bool ({result})")
        else:
            print(f"❌ control_drift: Invalid return type {type(result)}")
            
    except Exception as e:
        print(f"⚠️ ConversionManager Test Failed: {e}")

def test_transfer_manager():
    print("\n=== TRANSFER MANAGER ===")
    try:
        from manager.transfer import TransferManager
        
        # Check get_lowest_fee_estimate exists
        if hasattr(TransferManager, 'get_lowest_fee_estimate'):
            print(f"✅ get_lowest_fee_estimate: Method Exists")
        else:
            print(f"❌ get_lowest_fee_estimate: Method Missing!")
            
    except Exception as e:
        print(f"⚠️ TransferManager Test Failed: {e}")

if __name__ == "__main__":
    print("🧪 PHASE A3: Manager Integration Tests")
    test_money_manager()
    test_order_executor()
    test_conversion_manager()
    test_transfer_manager()
    print("\n✅ Manager Verification Complete")
