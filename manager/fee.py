import logging
from decimal import Decimal
from typing import Dict, Optional
from domain.entities import Symbol, FeeStructure
from manager.registry import MarketRegistry
from dotenv import load_dotenv
import os
import time

load_dotenv()

logger = logging.getLogger(__name__)

class FeeManager:
    def __init__(self, config: dict, exchanges: Dict, registry: MarketRegistry = None):
        self.config = config
        self.exchanges = exchanges
        self.registry = registry
        self.fee_structures: Dict[str, FeeStructure] = {}
        self._cache = {}  # Memory cache
        self.cache_ttl = config.get('cache_ttl_minutes', 5) * 60
        self.retry_count = config.get('retry_count', 3)
        self._fetch_fee_structures()

    def _fetch_fee_structures(self):
        for name, exchange in self.exchanges.items():
            for attempt in range(self.retry_count):
                try:
                    fees_standard = exchange.fetch_fees()
                    self.fee_structures[name] = FeeStructure(
                        exchange=name,
                        maker_fee=fees_standard['maker'],
                        taker_fee=fees_standard['taker'],
                        bnb_discount=fees_standard['bnb_discount']
                    )
                    self._cache[name] = {'fees': fees_standard['raw'], 'timestamp': time.time()}
                    logger.info(f"Fetched standardized fees from Port for {name}")
                    break
                except Exception as e:
                    logger.warning(f"Fee fetch attempt {attempt+1} failed for {name}: {e}")
                    if attempt == self.retry_count - 1:
                        logger.error(f"Max retries reached for {name} fees - halting")
                        raise Exception(f"Failed to fetch fees for {name}")
                    time.sleep(1)

    def calculate_optimal_route(self, symbol: Symbol, amount_usd: Decimal) -> tuple[str, str, Decimal]:
        available = self.fee_structures.copy()
        best_buy = None
        best_sell = None
        lowest_fee_pair = Decimal('999')
        for buy_ex in available:
            for sell_ex in available:
                if buy_ex == sell_ex:
                    continue
                buy_fee = self.get_effective_fee(buy_ex, amount_usd, is_maker=False)
                sell_fee = self.get_effective_fee(sell_ex, amount_usd, is_maker=False)
                total_fee = buy_fee + sell_fee
                if total_fee < lowest_fee_pair:
                    lowest_fee_pair = total_fee
                    best_buy = buy_ex
                    best_sell = sell_ex
        estimated_profit = self._estimate_profit_after_fees(symbol, amount_usd, best_buy, best_sell)
        return best_buy, best_sell, estimated_profit

    def get_effective_fee(self, exchange: str, amount_usd: Decimal, is_maker: bool) -> Decimal:
        if exchange not in self.fee_structures:
            return Decimal('0.001')
        fee_struct = self.fee_structures[exchange]
        base_fee = fee_struct.maker_fee if is_maker else fee_struct.taker_fee
        if fee_struct.zero_fee_remaining > 0:
            return Decimal('0')
        if fee_struct.bnb_discount:
            return base_fee * (1 - fee_struct.bnb_discount_pct)
        return base_fee

    def _estimate_profit_after_fees(self, symbol: Symbol, amount_usd: Decimal, buy_ex: str, sell_ex: str) -> Decimal:
        spread_profit = amount_usd * Decimal('0.005')
        buy_fee = amount_usd * self.get_effective_fee(buy_ex, amount_usd, False)
        sell_fee = amount_usd * self.get_effective_fee(sell_ex, amount_usd, False)
        net_profit = spread_profit - buy_fee - sell_fee
        return net_profit