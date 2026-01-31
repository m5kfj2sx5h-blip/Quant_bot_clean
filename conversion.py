"""
Conversion Manager - Proper Decimal Usage and Triangular Execution
Per improvements.md: Small accounts MUST use same-exchange triangular as primary strategy
"""
import itertools
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

class ConversionManager:
    """
    Manages internal conversions (triangular arbitrage) to rebalance capital without transfers.
    All money calculations use Decimal per architecture requirements.
    """
    def __init__(self, config: Dict = None, exchanges: Dict = None, order_executor=None, portfolio=None):
        self.config = config or {}
        self.exchanges = exchanges or {}
        self.order_executor = order_executor
        self.portfolio = portfolio
        self.logger = logging.getLogger(__name__)

        # Per improvements.md section 3.1: Min spread > 3× fee
        # Assume 0.1% per trade, so 0.3% total → require 0.4% min for safety
        self.min_profit_pct = Decimal(str(self.config.get('min_conversion_profit_pct', '0.4')))

        # Per improvements.md section 3.2: ≤10% of equity per cycle
        self.max_position_pct = Decimal(str(self.config.get('max_triangular_position_pct', '0.10')))

        self.drift_threshold = Decimal('0.15')
        self.capital_mode = "balanced"

        self.logger.info(f"ConversionManager initialized: min_profit={float(self.min_profit_pct)}%, max_position={float(self.max_position_pct*100)}% TPV")

    def detect_triangle(
        self,
        books: Dict[str, Dict[str, Dict]],
        fee_schedule: Dict[str, Decimal],
        specified_pairs: List[str] = None,
        exchanges: List[str] = None
    ) -> List[Dict]:
        """
        Detect triangular arbitrage opportunities with PROPER Decimal usage and fee modeling.

        Args:
            books: Registry format {exchange: {symbol: {'bid': Decimal, 'ask': Decimal, 'bids': [...], 'asks': [...]}}}
            fee_schedule: {exchange: Decimal} - taker fee per leg (e.g., 0.001 for 0.1%)
            specified_pairs: Optional list of pairs to check (for drift-specific scanning)
            exchanges: Optional list of exchanges to check

        Returns:
            List of opportunities sorted by profit_pct DESC
        """
        min_prof = self.min_profit_pct
        opportunities = []

        pairs_to_check = specified_pairs or self._fetch_pairs_from_books(books)

        # Safety: Clamp to 15 pairs max to prevent O(N^3) explosion
        if len(pairs_to_check) > 15:
            self.logger.debug(f"Clamping triangular search from {len(pairs_to_check)} to 15 pairs")
            pairs_to_check = pairs_to_check[:15]

        exchanges_to_check = exchanges or list(books.keys())

        # Generate all 3-pair permutations
        paths = list(itertools.permutations(pairs_to_check, 3))
        self.logger.debug(f"Checking {len(paths)} triangular paths across {len(exchanges_to_check)} exchanges (min profit: {float(min_prof)}%)")

        for path in paths:
            for ex in exchanges_to_check:
                try:
                    # Verify all pairs exist for this exchange
                    if not all(pair in books.get(ex, {}) for pair in path):
                        continue

                    # Get fee for this exchange (fallback to 0.1% if not in schedule)
                    fee_per_leg = fee_schedule.get(ex, Decimal('0.001'))

                    # Extract order book data - Registry format uses {'bid': Decimal, 'ask': Decimal, 'bids': [...], 'asks': [...]}
                    pair1_book = books[ex][path[0]]
                    pair2_book = books[ex][path[1]]
                    pair3_book = books[ex][path[2]]

                    # For triangular: buy pair1 (ask), buy pair2 (ask), sell pair3 (bid)
                    # Example: USDT -> BTC (buy BTC/USDT ask) -> ETH (buy ETH/BTC ask) -> USDT (sell ETH/USDT bid)

                    # Use best ask for legs 1 & 2, best bid for leg 3
                    price_leg1 = Decimal(str(pair1_book['asks'][0]['price'])) if pair1_book.get('asks') else Decimal(str(pair1_book['ask']))
                    price_leg2 = Decimal(str(pair2_book['asks'][0]['price'])) if pair2_book.get('asks') else Decimal(str(pair2_book['ask']))
                    price_leg3 = Decimal(str(pair3_book['bids'][0]['price'])) if pair3_book.get('bids') else Decimal(str(pair3_book['bid']))

                    # Validate non-zero prices
                    if price_leg1 <= 0 or price_leg2 <= 0 or price_leg3 <= 0:
                        continue

                    # Calculate profit with FEE DEDUCTION (per improvements.md)
                    # Start with 1 unit of starting currency
                    start_amount = Decimal('1')

                    # Leg 1: Buy at price_leg1, pay fee
                    after_leg1 = (start_amount / price_leg1) * (Decimal('1') - fee_per_leg)

                    # Leg 2: Buy at price_leg2, pay fee
                    after_leg2 = (after_leg1 / price_leg2) * (Decimal('1') - fee_per_leg)

                    # Leg 3: Sell at price_leg3, pay fee
                    final_amount = after_leg2 * price_leg3 * (Decimal('1') - fee_per_leg)

                    # Profit percentage
                    profit_pct = (final_amount - Decimal('1')) * Decimal('100')

                    if profit_pct > min_prof:
                        # Calculate available depth (sum of top 5 levels)
                        depth_leg1 = sum(Decimal(str(level['amount'])) for level in pair1_book.get('asks', [])[:5])
                        depth_leg2 = sum(Decimal(str(level['amount'])) for level in pair2_book.get('asks', [])[:5])
                        depth_leg3 = sum(Decimal(str(level['amount'])) for level in pair3_book.get('bids', [])[:5])

                        opportunities.append({
                            'exchange': ex,
                            'path': path,
                            'profit_pct': profit_pct,  # Keep as Decimal
                            'prices': {
                                'leg1': price_leg1,
                                'leg2': price_leg2,
                                'leg3': price_leg3
                            },
                            'depth': {
                                'leg1': depth_leg1,
                                'leg2': depth_leg2,
                                'leg3': depth_leg3
                            },
                            'fee_per_leg': fee_per_leg,
                            'final_multiplier': final_amount  # How much we get back per 1 unit invested
                        })

                except (KeyError, IndexError, ValueError, TypeError, ZeroDivisionError) as e:
                    # Missing book data or calculation error
                    continue
                except Exception as e:
                    self.logger.debug(f"Unexpected error in triangular path check {path} on {ex}: {e}")
                    continue

        # Sort by profit_pct descending
        return sorted(opportunities, key=lambda x: x['profit_pct'], reverse=True)

    def execute_best_triangular(
        self,
        opportunities: List[Dict],
        max_trade_usd: Decimal
    ) -> Tuple[bool, Optional[Dict]]:
        """
        Execute the best triangular opportunity using OrderExecutor.

        Args:
            opportunities: Sorted list from detect_triangle()
            max_trade_usd: Maximum USD equivalent to trade (portfolio.total_value_usd * max_position_pct)

        Returns:
            (success: bool, trade_record: Dict or None)
        """
        if not opportunities:
            return False, None

        if not self.order_executor:
            self.logger.error("No OrderExecutor available for triangular execution")
            return False, None

        best_opp = opportunities[0]
        exchange_id = best_opp['exchange']
        path = best_opp['path']

        # Calculate trade size
        # Limited by: (1) max_trade_usd, (2) available depth, (3) current balance
        trade_size_usd = self._calculate_safe_trade_size(best_opp, max_trade_usd)

        if trade_size_usd < Decimal('10'):  # Min $10 per trade
            self.logger.warning(f"Trade size ${trade_size_usd} too small (min $10)")
            return False, None

        self.logger.info(f"🔄 Executing triangular on {exchange_id}: {' -> '.join(path)}")
        self.logger.info(f"   Profit: {float(best_opp['profit_pct']):.3f}% | Size: ${float(trade_size_usd):.2f}")

        # Call OrderExecutor.execute_triangular()
        # This method already exists in order_executor.py lines 132-224
        success = asyncio.run(
            self.order_executor.execute_triangular(
                exchange_id=exchange_id,
                path=list(path),
                trade_value=trade_size_usd,
                start_currency='USDT'  # Assuming USDT start
            )
        )

        if success:
            trade_record = {
                'type': 'TRIANGULAR',
                'exchange': exchange_id,
                'path': ' -> '.join(path),
                'expected_profit_pct': best_opp['profit_pct'],
                'size_usd': trade_size_usd
            }
            return True, trade_record

        return False, None

    def control_drift(
        self,
        drift_data: List[tuple],
        books: Dict = None,
        fee_schedule: Dict[str, Decimal] = None
    ) -> bool:
        """
        PRIMARY STRATEGY: Execute triangular arbitrage to fix drift without transfers.
        Per improvements.md: This should be the MAIN approach for small accounts.

        Args:
            drift_data: [(asset, deviation), ...] where deviation is Decimal
            books: Registry order books
            fee_schedule: {exchange: Decimal} taker fees

        Returns:
            True if action taken, False otherwise
        """
        if not drift_data:
            return False

        if not books:
            self.logger.warning("No order book data available for conversion analysis")
            return False

        if not fee_schedule:
            # Fallback: Assume 0.1% taker fee everywhere
            fee_schedule = {ex: Decimal('0.001') for ex in books.keys()}

        action_taken = False

        # Calculate max trade size (10% of TPV per improvements.md)
        if self.portfolio and self.portfolio.total_value_usd > 0:
            max_trade_usd = self.portfolio.total_value_usd * self.max_position_pct
        else:
            max_trade_usd = Decimal('100')  # Fallback min

        for asset, deviation in drift_data:
            self.logger.info(f"Analyzing conversion for {asset} (drift: {float(deviation)*100:.2f}%)")

            # Get all pairs involving this asset
            asset_pairs = self._get_pairs_for_asset(asset, books)

            if len(asset_pairs) < 3:  # Need at least 3 pairs for triangular
                self.logger.debug(f"Not enough pairs for {asset} triangular ({len(asset_pairs)} found)")
                continue

            # Detect opportunities
            opportunities = self.detect_triangle(
                books=books,
                fee_schedule=fee_schedule,
                specified_pairs=asset_pairs,
                exchanges=None  # Check all exchanges
            )

            if opportunities:
                # Execute best opportunity
                success, trade_record = self.execute_best_triangular(opportunities, max_trade_usd)

                if success:
                    self.logger.info(f"✅ Triangular executed successfully: {trade_record}")
                    action_taken = True
                    break  # Only execute one per drift check to avoid overtrading
                else:
                    self.logger.warning(f"❌ Triangular execution failed for {asset}")
            else:
                self.logger.debug(f"No profitable triangular routes for {asset} (min: {float(self.min_profit_pct)}%)")

        if not action_taken:
            self.logger.info("Internal Conversion: No profitable opportunities above threshold")

        return action_taken

    # Helper methods

    def _fetch_pairs_from_books(self, books: Dict) -> List[str]:
        """Extract unique pairs from order books."""
        pairs = set()
        for ex_books in books.values():
            pairs.update(ex_books.keys())
        return list(pairs)

    def _get_pairs_for_asset(self, asset: str, books: Dict) -> List[str]:
        """Get all pairs containing the specified asset."""
        pairs = set()
        for ex_books in books.values():
            for pair in ex_books.keys():
                if asset in pair or asset.replace('/', '') in pair:
                    pairs.add(pair)
        return list(pairs)

    def _calculate_safe_trade_size(self, opportunity: Dict, max_usd: Decimal) -> Decimal:
        """
        Calculate safe trade size limited by depth, balance, and max position.
        Per improvements.md: Add 0.05-0.15% slippage buffer.
        """
        # Get minimum depth across all 3 legs (in base currency)
        min_depth = min(
            opportunity['depth']['leg1'],
            opportunity['depth']['leg2'],
            opportunity['depth']['leg3']
        )

        # Convert depth to USD using first leg price
        depth_usd = min_depth * opportunity['prices']['leg1']

        # Apply slippage safety: only use 50% of available depth
        safe_depth_usd = depth_usd * Decimal('0.5')

        # Take minimum of max allowed and safe depth
        trade_size = min(max_usd, safe_depth_usd)

        # Round down to 2 decimals
        return trade_size.quantize(Decimal('0.01'), rounding=ROUND_DOWN)

    def update_capital_mode(self, drift_data: List[tuple], total_stablecoins: Decimal, bottleneck_threshold: Decimal = Decimal('1500')):
        """Update capital mode based on drift and stable balance."""
        if not drift_data:
            max_deviation = Decimal('0')
        else:
            max_deviation = max((dev for _, dev in drift_data), default=Decimal('0'))

        if max_deviation >= self.drift_threshold or total_stablecoins < bottleneck_threshold:
            self.capital_mode = "bottlenecked"
        else:
            self.capital_mode = "balanced"

        self.logger.info(
            f"Capital mode: {self.capital_mode} "
            f"(max drift {float(max_deviation)*100:.1f}%, stables ${float(total_stablecoins):.0f})"
        )


# Import asyncio for execute_triangular call
import asyncio
