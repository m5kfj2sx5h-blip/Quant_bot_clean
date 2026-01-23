"""
# responsible for all conversions from one form of money to another outside triangular arbitrage.
# an on demand triangular arbitrage machine with specified pairs and finds the cheapest AND fastest routes for the [MONEY MANAGER].
# tries to keep the drift across accounts below 15% by intra-exchange triangular conversions, so [[Q-bot]] runs smoothly.
# Does not interrupt arbitrage system

## One job: Reduces the amount needed to transfer by prioritizing triangular conversions (intra-exchange) over any cross-account transfers whenever possible to eliminate transfer fees entirely.

# originally triangular.py #  redone

COINVERSION MANAGER - INTRA-EXCHANGE- Triangular arbitrage
"""
import itertools
import logging
from decimal import Decimal
import os
from core.health_monitor import HealthMonitor  # For exchange latency
from manager.transfer import TransferManager  # For fallback transfers
from manager.scanner import MarketContext  # For current books
from core.order_executor import OrderExecutor  # For executing route

log = logging.getLogger('tri')

PAIRS = ['BTC-USD','ETH-USD','SOL-USD','BTC-USDT','ETH-USDT','SOL-USDT','BTC-USDC','ETH-USDC','SOL-USDC','BTC-USDG','ETH-USDG','SOL-USDG' 'ETH-BTC','SOL-BTC','SOL-ETH','BTC-PAXG','PAXG-ETH','SOL-PAXG','USD-USDT','USDT-USDC','USD-USDC','USD-USDG','USDG-USDT','USDG-USDC']  # Expanded for more routes
PATHS = list(itertools.permutations(['BTC','ETH','SOL','PAXG','USD','USDT','USDC','USDG'], 3))

def detect_triangle(books, specified_pairs=None, exchanges=None, min_prof=Decimal('0.08')):
    """
    books dict  {'exchange': {'BTC-USD':{bids:[],asks:[]}, ...}
    returns [{'path':USD→BTC→ETH→USD, 'ex':kraken, 'prof_pct':0.11}, ...]
    """
    out = []
    paths = list(itertools.permutations(specified_pairs or PAIRS, 3))  # On-demand pairs or default
    exchanges = exchanges or list(books.keys())  # On-demand exchanges or all
    health = HealthMonitor()  # For latency
    for p in paths:
        for ex in exchanges:
            try:
                a = Decimal(books[ex][f'{p[1]}-{p[0]}']['asks'][0][0])   # USD→BTC
                b = Decimal(books[ex][f'{p[2]}-{p[1]}']['asks'][0][0])   # BTC→ETH
                c = Decimal(books[ex][f'{p[0]}-{p[2]}']['bids'][0][0])   # ETH→USD
                prof = (Decimal('1')/a * Decimal('1')/b * c - Decimal('1')) * Decimal('100')
                if prof > min_prof:
                    latency = health.latency_metrics[ex][-1] if health.latency_metrics[ex] else Decimal('0')  # Fastest route
                    out.append({'ex':ex, 'path':p, 'prof_pct':prof, 'latency_ms':latency})
            except:
                continue
    # Sort by cheapest (prof desc), then fastest (latency asc)
    return sorted(out, key=lambda x: (-x['prof_pct'], x['latency_ms']))

def control_drift(self, drift_data):
    """Control drift via intra-triangular conversions to eliminate transfer fees."""
    # Drift control - prioritize intra-triangular to eliminate fees
    drift_data = []
    for asset, current in current_allocations.items():
        target = self.MACRO_TARGET_ALLOCATIONS.get(asset, Decimal('0'))
        deviation = abs(current - target)
        if deviation >= Decimal('0.15'):  # 15% drift threshold for intra
            drift_data.append((asset, deviation))

    if drift_data:
        if self.conversion_manager.control_drift(drift_data):
            self.logger.info(f"Drift controlled via intra-triangular for {len(drift_data)} assets — no transfer fees")
        else:
            self.logger.warning(f"Drift >=15% for {len(drift_data)} assets — no intra route, manual transfer needed")

    for asset, deviation in drift_data:
        # Placeholder — integrate real books from scanner/feed later
        scanner = MarketContext(config={}, logger=logging.getLogger(__name__))  # Init with config if needed
        books = scanner.order_book_history  # Latest books from scanner
        if not books:
            self.logger.warning("No current books available for drift control")
            return False

        routes = self.detect_triangle(books)
        if routes:
            top = routes[0]
            self.logger.info(f"Intra-triangular drift control for {asset}: {top['path']} prof {top['prof_pct']}%")
            order_executor = OrderExecutor()  # Init if needed
            path = top['path']  # e.g., ('USDT', 'BTC', 'ETH')
            # Execute a->b->c spot trades (long only)
            # Example: buy BTC with USDT, buy ETH with BTC, sell ETH for USDT
            try:
                # First leg: USDT -> BTC
                order_executor.execute_arbitrage(buy_exchange=top['ex'], sell_exchange=top['ex'],
                                                 symbol=f"{path[0]}{path[1]}", position_size=deviation,
                                                 expected_profit=Decimal('0'))  # Simplified
                # Second leg: BTC -> ETH
                order_executor.execute_arbitrage(buy_exchange=top['ex'], sell_exchange=top['ex'],
                                                 symbol=f"{path[1]}{path[2]}", position_size=deviation,
                                                 expected_profit=Decimal('0'))
                # Third leg: ETH -> USDT
                order_executor.execute_arbitrage(buy_exchange=top['ex'], sell_exchange=top['ex'],
                                                 symbol=f"{path[2]}{path[0]}", position_size=deviation,
                                                 expected_profit=Decimal('0'))
                self.logger.info(f"Executed intra-triangular route {path} on {top['ex']} for drift control")
                return True
            except Exception as e:
                self.logger.error(f"Triangular execution failed: {e}")

                return False


            return True


    return False

# Update capital mode after drift check
max_deviation = max((dev for _, dev in drift_data), default=Decimal('0'))
total_stable = sum(total_values.get(c, Decimal('0')) for c in ['USDT', 'USDC', 'USD'])
if max_deviation >= Decimal('0.15') or total_stable < Decimal('1500'):
    self.capital_mode = "bottlenecked"
else:
    self.capital_mode = "balanced"
self.logger.info(f"Capital mode: {self.capital_mode} (max drift {max_deviation*100:.1f}%, stable ${total_stable:.0f})")