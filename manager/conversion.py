import itertools
import logging
from decimal import Decimal
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class ConversionManager:
    def __init__(self, config: Dict = None, exchanges: Dict = None):
        self.config = config or {}
        self.exchanges = exchanges or {}
        self.logger = logging.getLogger(__name__)
        self.capital_mode = "balanced"
        self.drift_threshold = Decimal('0.15')
        self.min_profit_pct = Decimal('0.08')

    def detect_triangle(self, books: Dict, specified_pairs: List = None, exchanges: List = None, min_prof: Decimal = None) -> List[Dict]:
        min_prof = min_prof or self.min_profit_pct
        out = []
        
        # GNN Path (More efficient)
        if self.config.get('USE_GNN', False):
            try:
                from manager.gnn_detector import GNNArbitrageDetector, GNN_AVAILABLE
                if GNN_AVAILABLE:
                    # Initialize detector if not exists (lightweight)
                    if not hasattr(self, '_gnn_detector'):
                        self._gnn_detector = GNNArbitrageDetector(min_profit=float(min_prof))
                    
                    # Run detection on provided books
                    # Note: GNN expects {ex: {pair: book}}, verify structure
                    cycles = self._gnn_detector.detect(books, max_length=3)
                    
                    for cycle in cycles:
                        # Convert GNN cycle to legacy format for compatibility
                        if len(cycle['path']) != 3: continue 
                        
                        # Reconstruct path details
                        # GNN returns assets [A, B, C], we need pairs [A/B, B/C, C/A]
                        path_assets = cycle['path']
                        path_pairs = []
                        valid_cycle = True
                        prices = {}
                        
                        # Find the specific pairs used (limited attempt to reconstruct)
                        # This is tricky because GNN abstracts pairs. 
                        # Ideally GNN should return pair info, but we can infer.
                        # For ConversionManager, we mostly care that a path EXISTS.
                        
                        # Allow GNN result to pass through if it matches requested exchanges
                        # Conversion logic usually needs specific pairs to execute.
                        # For now, we will trust the GNN profit but fallback to permutation 
                        # if we need strict pair validation for execution, 
                        # OR we just let the legacy runner handle execution details 
                        # if GNN is purely for detection speed.
                        
                        # BETTER APPROACH: Use GNN to finding candidate assets, then verify pairs.
                        pass # GNN integration in conversion manager is tricky without refactoring execution.
                        # Strategy: If GNN finds a cycle on Exchange X involving Asset A, B, C
                        # We construct the tuple and add it.
            except Exception as e:
                self.logger.debug(f"GNN Conversion detect error: {e}")

        # Legacy Permutation Logic (Robust & Exact for Execution)
        pairs_to_check = specified_pairs or self._fetch_pairs()
        exchanges_to_check = exchanges or list(books.keys())
        paths = list(itertools.permutations(pairs_to_check, 3))
        for path in paths:
            for ex in exchanges_to_check:
                try:
                    p0_base, p0_quote = path[0].split('-')
                    p1_base, p1_quote = path[1].split('-')
                    p2_base, p2_quote = path[2].split('-')
                    if path[0] not in books.get(ex, {}): continue
                    if path[1] not in books.get(ex, {}): continue
                    if path[2] not in books.get(ex, {}): continue
                    a = books[ex][path[0]]['asks'][0][0]
                    b = books[ex][path[1]]['asks'][0][0]
                    c = books[ex][path[2]]['bids'][0][0]
                    prof = (Decimal('1') / a * Decimal('1') / b * c - Decimal('1')) * Decimal('100')
                    if prof > min_prof:
                        out.append({
                            'exchange': ex,
                            'path': path,
                            'profit_pct': float(prof),
                            'prices': {'a': float(a), 'b': float(b), 'c': float(c)}
                        })
                        self.logger.info(f"Fetched triangular path from API for {ex}")
                except (KeyError, IndexError, ZeroDivisionError):
                    continue
                except Exception as e:
                    self.logger.debug(f"Triangle detection error: {e}")
                    continue
        return sorted(out, key=lambda x: -x['profit_pct'])

    def _fetch_pairs(self) -> List[str]:
        pairs = []
        for exchange in self.exchanges.values():
            markets = exchange.get_supported_pairs()
            for symbol in markets:
                pair = str(symbol).replace('/', '-')
                if pair not in pairs:
                    pairs.append(pair)
        return pairs

    def control_drift(self, drift_data: List[tuple], books: Dict = None) -> bool:
        if not drift_data:
            return True
        if not books:
            self.logger.warning("No order books available for drift control")
            return False
        for asset, deviation in drift_data:
            routes = self.detect_triangle(books)
            if routes:
                top = routes[0]
                self.logger.info(f"Found triangular route for {asset} drift control: {top['path']} on {top['exchange']} ({top['profit_pct']:.2f}% profit)")
                return True
            else:
                self.logger.warning(f"No triangular route for {asset} (deviation: {float(deviation)*100:.1f}%) - manual transfer may be needed")
        return False

    def update_capital_mode(self, drift_data: List[tuple], total_stablecoins: Decimal, bottleneck_threshold: Decimal = Decimal('1500')):
        if not drift_data:
            max_deviation = Decimal('0')
        else:
            max_deviation = max((dev for _, dev in drift_data), default=Decimal('0'))
        if max_deviation >= self.drift_threshold or total_stablecoins < bottleneck_threshold:
            self.capital_mode = "bottlenecked"
        else:
            self.capital_mode = "balanced"
        self.logger.info(f"Capital mode: {self.capital_mode} (max drift {float(max_deviation)*100:.1f}%, stables ${float(total_stablecoins):.0f}, threshold ${float(bottleneck_threshold):.0f})")

    def get_best_conversion_route(self, from_asset: str, to_asset: str, exchange: str, books: Dict) -> Optional[Dict]:
        direct_pair = f"{from_asset}-{to_asset}"
        reverse_pair = f"{to_asset}-{from_asset}"
        if exchange in books:
            if direct_pair in books[exchange]:
                return {'type': 'direct', 'pair': direct_pair, 'exchange': exchange, 'legs': 1}
            if reverse_pair in books[exchange]:
                return {'type': 'direct_reverse', 'pair': reverse_pair, 'exchange': exchange, 'legs': 1}
        for intermediate in ['BTC', 'ETH', 'SOL']:
            if intermediate == from_asset or intermediate == to_asset:
                continue
            leg1 = f"{from_asset}-{intermediate}"
            leg2 = f"{intermediate}-{to_asset}"
            if exchange in books:
                if leg1 in books[exchange] and leg2 in books[exchange]:
                    return {'type': 'triangular', 'path': [leg1, leg2], 'exchange': exchange, 'legs': 2}
        return None