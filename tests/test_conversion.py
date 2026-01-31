"""
Unit tests for ConversionManager
Verifies Decimal precision and fee-aware profit calculations
"""
import sys
sys.path.insert(0, '/Users/dj3bosmacbookpro/Desktop/quant_bot_FIXED')

from decimal import Decimal
from conversion import ConversionManager

def test_triangular_profit_calculation():
    """
    Test Case: USDT -> BTC -> ETH -> USDT triangular arbitrage

    Given:
    - BTC/USDT ask: 60,000 (we buy BTC)
    - ETH/BTC ask: 0.05 (we buy ETH with BTC)
    - ETH/USDT bid: 3,100 (we sell ETH for USDT)
    - Fee per leg: 0.1% (0.001)

    Expected:
    - After leg 1: 1 USDT / 60000 * 0.999 = 0.00001665 BTC
    - After leg 2: 0.00001665 / 0.05 * 0.999 = 0.000332667 ETH
    - After leg 3: 0.000332667 * 3100 * 0.999 = 1.03070877 USDT
    - Profit: 3.07%
    """

    print("Test 1: Triangular Profit Calculation with Fees")
    print("=" * 60)

    # Setup
    config = {'min_conversion_profit_pct': '0.3'}
    manager = ConversionManager(config=config)

    # Mock order books in Registry format
    books = {
        'binanceus': {
            'BTC/USDT': {
                'bid': Decimal('59900'),
                'ask': Decimal('60000'),
                'bids': [{'price': Decimal('59900'), 'amount': Decimal('1.0')}],
                'asks': [{'price': Decimal('60000'), 'amount': Decimal('1.0')}]
            },
            'ETH/BTC': {
                'bid': Decimal('0.0499'),
                'ask': Decimal('0.05'),
                'bids': [{'price': Decimal('0.0499'), 'amount': Decimal('10.0')}],
                'asks': [{'price': Decimal('0.05'), 'amount': Decimal('10.0')}]
            },
            'ETH/USDT': {
                'bid': Decimal('3100'),
                'ask': Decimal('3150'),
                'bids': [{'price': Decimal('3100'), 'amount': Decimal('5.0')}],
                'asks': [{'price': Decimal('3150'), 'amount': Decimal('5.0')}]
            }
        }
    }

    fee_schedule = {'binanceus': Decimal('0.001')}  # 0.1% per leg

    # Execute detection
    opportunities = manager.detect_triangle(
        books=books,
        fee_schedule=fee_schedule,
        specified_pairs=['BTC/USDT', 'ETH/BTC', 'ETH/USDT'],
        exchanges=['binanceus']
    )

    # Verify
    print(f"Opportunities found: {len(opportunities)}")

    if opportunities:
        best = opportunities[0]
        print(f"\nBest Opportunity:")
        print(f"  Exchange: {best['exchange']}")
        print(f"  Path: {' -> '.join(best['path'])}")
        print(f"  Profit: {float(best['profit_pct']):.4f}%")
        print(f"  Prices: L1={float(best['prices']['leg1'])}, L2={float(best['prices']['leg2'])}, L3={float(best['prices']['leg3'])}")
        print(f"  Final multiplier: {float(best['final_multiplier']):.8f}x")

        # Manual calculation to verify
        start = Decimal('1')
        after_leg1 = (start / best['prices']['leg1']) * (Decimal('1') - best['fee_per_leg'])
        after_leg2 = (after_leg1 / best['prices']['leg2']) * (Decimal('1') - best['fee_per_leg'])
        final = after_leg2 * best['prices']['leg3'] * (Decimal('1') - best['fee_per_leg'])
        profit_manual = (final - Decimal('1')) * Decimal('100')

        print(f"\nManual Verification:")
        print(f"  After leg 1: {float(after_leg1):.10f} BTC")
        print(f"  After leg 2: {float(after_leg2):.10f} ETH")
        print(f"  Final USDT: {float(final):.10f}")
        print(f"  Profit: {float(profit_manual):.4f}%")

        # Assert profit matches
        assert abs(best['profit_pct'] - profit_manual) < Decimal('0.0001'), "Profit calculation mismatch!"
        print(f"\n✅ PASS: Profit calculation verified!")

        # Verify it's above threshold
        assert best['profit_pct'] > Decimal('0.3'), f"Profit {float(best['profit_pct'])}% should be > 0.3%"
        print(f"✅ PASS: Profit above minimum threshold (0.3%)")

    else:
        print("❌ FAIL: No opportunities detected (expected 1)")
        return False

    return True


def test_unprofitable_triangular():
    """
    Test Case: Triangular that appears profitable but ISN'T after fees

    Given:
    - Theoretical gross profit: 0.25%
    - Fees: 3 × 0.1% = 0.3%
    - Net profit: -0.05% (LOSS)

    Expected: Should NOT be detected
    """

    print("\n\nTest 2: Unprofitable Triangular (Below Fee Threshold)")
    print("=" * 60)

    config = {'min_conversion_profit_pct': '0.3'}
    manager = ConversionManager(config=config)

    # Mock books with tight spreads
    books = {
        'kraken': {
            'BTC/USD': {
                'bid': Decimal('60000'),
                'ask': Decimal('60050'),  # Tight spread
                'asks': [{'price': Decimal('60050'), 'amount': Decimal('1.0')}]
            },
            'ETH/BTC': {
                'ask': Decimal('0.05'),
                'asks': [{'price': Decimal('0.05'), 'amount': Decimal('10.0')}]
            },
            'ETH/USD': {
                'bid': Decimal('3005'),  # Would give ~0.25% gross, but fees kill it
                'bids': [{'price': Decimal('3005'), 'amount': Decimal('5.0')}]
            }
        }
    }

    fee_schedule = {'kraken': Decimal('0.001')}

    opportunities = manager.detect_triangle(
        books=books,
        fee_schedule=fee_schedule,
        specified_pairs=['BTC/USD', 'ETH/BTC', 'ETH/USD'],
        exchanges=['kraken']
    )

    print(f"Opportunities found: {len(opportunities)}")

    if opportunities:
        best = opportunities[0]
        print(f"❌ FAIL: Detected unprofitable opportunity: {float(best['profit_pct']):.4f}%")
        return False
    else:
        print(f"✅ PASS: Correctly rejected unprofitable triangular")
        return True


def test_decimal_precision():
    """
    Test Case: Verify NO float() conversions in calculations

    All internal calculations must use Decimal to avoid rounding errors
    """

    print("\n\nTest 3: Decimal Precision (No Float Contamination)")
    print("=" * 60)

    config = {}
    manager = ConversionManager(config=config)

    books = {
        'test_ex': {
            'A/B': {
                'ask': Decimal('1.23456789012345'),  # High precision
                'asks': [{'price': Decimal('1.23456789012345'), 'amount': Decimal('1.0')}]
            },
            'B/C': {
                'ask': Decimal('2.34567890123456'),
                'asks': [{'price': Decimal('2.34567890123456'), 'amount': Decimal('1.0')}]
            },
            'A/C': {
                'bid': Decimal('3.00000000000001'),
                'bids': [{'price': Decimal('3.00000000000001'), 'amount': Decimal('1.0')}]
            }
        }
    }

    fee_schedule = {'test_ex': Decimal('0')}  # No fees for precision test

    opportunities = manager.detect_triangle(
        books=books,
        fee_schedule=fee_schedule,
        specified_pairs=['A/B', 'B/C', 'A/C'],
        exchanges=['test_ex']
    )

    if opportunities:
        best = opportunities[0]

        # Verify all prices are Decimal
        assert isinstance(best['prices']['leg1'], Decimal), "Price leg1 should be Decimal"
        assert isinstance(best['prices']['leg2'], Decimal), "Price leg2 should be Decimal"
        assert isinstance(best['prices']['leg3'], Decimal), "Price leg3 should be Decimal"
        assert isinstance(best['profit_pct'], Decimal), "Profit should be Decimal"
        assert isinstance(best['final_multiplier'], Decimal), "Multiplier should be Decimal"

        print(f"✅ PASS: All money values are Decimal type")
        print(f"   Sample profit_pct type: {type(best['profit_pct'])}")
        print(f"   Sample profit_pct value: {best['profit_pct']}")

        return True
    else:
        print("❌ FAIL: No opportunity detected")
        return False


if __name__ == '__main__':
    print("ConversionManager Unit Tests")
    print("=" * 60)

    results = []

    try:
        results.append(("Triangular Profit Calc", test_triangular_profit_calculation()))
    except Exception as e:
        print(f"❌ Test 1 ERROR: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Triangular Profit Calc", False))

    try:
        results.append(("Unprofitable Detection", test_unprofitable_triangular()))
    except Exception as e:
        print(f"❌ Test 2 ERROR: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Unprofitable Detection", False))

    try:
        results.append(("Decimal Precision", test_decimal_precision()))
    except Exception as e:
        print(f"❌ Test 3 ERROR: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Decimal Precision", False))

    print("\n\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    total_passed = sum(1 for _, passed in results if passed)
    print(f"\nTotal: {total_passed}/{len(results)} tests passed")

    if total_passed == len(results):
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n⚠️  SOME TESTS FAILED")
        sys.exit(1)
