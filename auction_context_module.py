import logging
from typing import List, Tuple
from market_context import MarketContext, AuctionState

class AuctionContextModule:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def analyze_order_book(self, bids: List[Tuple[float, float]], 
                          asks: List[Tuple[float, float]], 
                          last_price: float,
                          context: MarketContext) -> MarketContext:
        """Analyze order book to determine auction context"""
        try:
            if not bids or not asks:
                return context
            
            # Calculate top 5 levels imbalance
            bid_vol = sum(qty for _, qty in bids[:5]) if len(bids[0]) > 1 else len(bids[:5])
            ask_vol = sum(qty for _, qty in asks[:5]) if len(asks[0]) > 1 else len(asks[:5])
            
            if bid_vol + ask_vol > 0:
                context.auction_imbalance_score = (bid_vol - ask_vol) / (bid_vol + ask_vol)
            
            # Determine auction state
            abs_score = abs(context.auction_imbalance_score)
            
            if abs_score < 0.1:
                context.auction_state = AuctionState.BALANCED
            elif context.auction_imbalance_score > 0.3:
                context.auction_state = AuctionState.IMBALANCED_BUYING
                context.crowd_behavior = "aggressive_buying"
            elif context.auction_imbalance_score < -0.3:
                context.auction_state = AuctionState.IMBALANCED_SELLING
                context.crowd_behavior = "aggressive_selling"
            elif 0.1 <= abs_score <= 0.3:
                # Check price acceptance
                best_bid = bids[0][0] if bids[0] else 0
                best_ask = asks[0][0] if asks[0] else 0
                
                if best_bid and best_ask:
                    mid_price = (best_bid + best_ask) / 2
                    
                    if abs(last_price - mid_price) / mid_price < 0.001:
                        context.auction_state = AuctionState.ACCEPTING
                        context.crowd_behavior = "accepting_prices"
                    elif last_price > best_ask and context.auction_imbalance_score < 0:
                        context.auction_state = AuctionState.REJECTING
                        context.crowd_behavior = "rejecting_high_prices"
                    elif last_price < best_bid and context.auction_imbalance_score > 0:
                        context.auction_state = AuctionState.REJECTING
                        context.crowd_behavior = "rejecting_low_prices"
                    else:
                        context.auction_state = AuctionState.BALANCED
                        context.crowd_behavior = "balanced"
            
            # Set key levels if we have order book data
            if bids and asks:
                context.key_support = bids[0][0] * 0.995 if bids[0][0] else None
                context.key_resistance = asks[0][0] * 1.005 if asks[0][0] else None
            
            # Calculate volume strength (simplified)
            total_vol = bid_vol + ask_vol
            context.volume_strength = min(total_vol / 100.0, 1.0)  # Normalized
            
            self.logger.debug(f"Auction Analysis: {context.auction_state.value} "
                            f"Score: {context.auction_imbalance_score:.3f} "
                            f"Confidence: {context.execution_confidence:.2f}")
            
        except Exception as e:
            self.logger.error(f"Auction analysis error: {e}")
        
        return context