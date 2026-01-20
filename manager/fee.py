"""
Fee optimization manager - calculates optimal order routing
"""
import logging
from decimal import Decimal
from typing import Dict, Optional

from ..domain.entities import Symbol, FeeStructure

logger = logging.getLogger(__name__)


class FeeManager:
    """Optimizes fees across exchanges"""

    def __init__(self, config: dict):
        self.config = config
        self.fee_structures: Dict[str, FeeStructure] = {}
        self._initialize_fee_structures()

    def _initialize_fee_structures(self):
        """Load fee structures from config"""
        exchanges = self.config.get('exchanges', {})

        for name, settings in exchanges.items():
            self.fee_structures[name] = FeeStructure(
                maker_fee=Decimal(str(settings.get('maker_fee', '0.001'))),
                taker_fee=Decimal(str(settings.get('taker_fee', '0.001'))),
                bnb_discount=Decimal(str(settings.get('bnb_discount', '0.05')))
            )

    def calculate_optimal_route(self, symbol: Symbol, amount_usd: Decimal) -> tuple[str, str, Decimal]:
        """
        Determine best buy/sell exchanges based on fees and liquidity
        Returns: (buy_exchange, sell_exchange, estimated_profit_after_fees)
        """
        # Prioritize: Kraken+ (free) > Coinbase One > BNB discount > others
        available = self.fee_structures.copy()

        # Remove unhealthy exchanges (would be tracked elsewhere)

        # Calculate effective fees
        best_buy = None
        best_sell = None
        lowest_fee_pair = Decimal('999')

        for buy_ex in available:
            for sell_ex in available:
                if buy_ex == sell_ex:
                    continue  # No same-exchange arbitrage

                buy_fee = self._get_effective_fee(buy_ex, amount_usd, is_maker=False)
                sell_fee = self._get_effective_fee(sell_ex, amount_usd, is_maker=False)
                total_fee = buy_fee + sell_fee

                if total_fee < lowest_fee_pair:
                    lowest_fee_pair = total_fee
                    best_buy = buy_ex
                    best_sell = sell_ex

        # Estimate profit after fees (simplified)
        estimated_profit = self._estimate_profit_after_fees(
            symbol, amount_usd, best_buy, best_sell
        )

        return best_buy, best_sell, estimated_profit

    def _get_effective_fee(self, exchange: str, amount_usd: Decimal, is_maker: bool) -> Decimal:
        """Get fee with all discounts applied"""
        if exchange not in self.fee_structures:
            return Decimal('0.001')  # Default 0.1%

        fee_struct = self.fee_structures[exchange]
        base_fee = fee_struct.maker_fee if is_maker else fee_struct.taker_fee

        # Apply exchange-specific discounts
        if exchange == 'binance' and self.config.get('binance', {}).get('use_bnb_discount', False):
            base_fee *= (Decimal('1') - fee_struct.bnb_discount)
        elif exchange in ['kraken', 'kraken_pro']:
            base_fee = Decimal('0')  # Free for pro users
        elif exchange == 'coinbase' and self.config.get('coinbase', {}).get('has_coinbase_one', False):
            base_fee *= Decimal('0.5')  # 50% discount with Coinbase One

        return base_fee

    def _estimate_profit_after_fees(self, symbol: Symbol, amount_usd: Decimal,
                                   buy_ex: str, sell_ex: str) -> Decimal:
        """Estimate profit after fees (simplified model)"""
        # Assume 0.5% spread minimum
        spread_profit = amount_usd * Decimal('0.005')

        # Deduct fees
        buy_fee = amount_usd * self._get_effective_fee(buy_ex, amount_usd, False)
        sell_fee = amount_usd * self._get_effective_fee(sell_ex, amount_usd, False)

        net_profit = spread_profit - buy_fee - sell_fee
        return net_profit
