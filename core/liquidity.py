import logging
from decimal import Decimal
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)

class LiquidityAnalyzer:
    """
    Analyzes Order Book depth to determine optimal trade size based on VWAP slippage.
    Eliminates 'All-or-Nothing' sizing logic.
    """
    
    @staticmethod
    def calculate_max_size_with_slippage(
        orders: List[Tuple[Decimal, Decimal]], 
        max_slippage_pct: Decimal
    ) -> Decimal:
        """
        Calculates the maximum volume one can consume from the order book
        before the VWAP price exceeds best_price * (1 + max_slippage).
        
        Args:
            orders: List of (price, amount) tuples, sorted best to worst.
            max_slippage_pct: Decimal (e.g. 0.005 for 0.5%).
            
        Returns:
            Decimal: Max tradeable volume (base asset).
        """
        if not orders:
            return Decimal('0')
            
        best_price = orders[0][0]
        if best_price <= 0:
            return Decimal('0')
            
        slippage_limit_price = best_price * (Decimal('1') + max_slippage_pct)
        
        total_vol = Decimal('0')
        total_cost = Decimal('0')
        
        for price, amount in orders:
            # Check if this single level already breaches limit? 
            # (Strict: VWAP must stay under. Relaxed: Marginal price stay under?)
            # We use VWAP constraint used by sophisticated bots.
            
            # Use entire level?
            next_vol = total_vol + amount
            next_cost = total_cost + (price * amount)
            next_vwap = next_cost / next_vol
            
            deviation = abs((next_vwap - best_price) / best_price)
            
            if deviation <= max_slippage_pct:
                # Accept full level
                total_vol = next_vol
                total_cost = next_cost
            else:
                # Partial fill of this level?
                # Math: (total_cost + price * x) / (total_vol + x) = best_price * (1+slip)
                # Solve for x.
                target_vwap = best_price * (Decimal('1') + max_slippage_pct)
                # total_cost + P*x = T_vwap * total_vol + T_vwap * x
                # P*x - T_vwap*x = T_vwap*total_vol - total_cost
                # x (P - T_vwap) = ...
                # x = (T_vwap * total_vol - total_cost) / (price - T_vwap) (Assuming Price > T_vwap for buy)
                
                # If price is lower than target (unlikely if strictly ascending?), we shouldn't be here unless previous levels messed up.
                # Simplified: Just stop at previous full level for robust safety.
                return total_vol
                
        return total_vol

    @staticmethod
    def get_vwap_for_size(orders: List[Tuple[Decimal, Decimal]], target_size: Decimal) -> Tuple[Decimal, Decimal]:
        """
        Calculates VWAP and Slippage % for a specific size.
        Returns: (vwap_price, slippage_pct)
        """
        if not orders or target_size <= 0:
            return Decimal('0'), Decimal('0')
            
        total_cost = Decimal('0')
        remaining = target_size
        best_price = orders[0][0]
        
        for price, amount in orders:
            take = min(remaining, amount)
            total_cost += price * take
            remaining -= take
            if remaining <= 0:
                break
                
        if remaining > 0:
            # Book not deep enough
            return Decimal('0'), Decimal('100.0') # Infinite slippage
            
        vwap = total_cost / target_size
        slippage = abs((vwap - best_price) / best_price)
        return vwap, slippage
