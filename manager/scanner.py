import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
import numpy as np
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal
import os
import statistics


class AuctionState(Enum):
    """Auction state enumeration"""
    OPEN = "open"
    CLOSED = "closed"
    PRE_OPEN = "pre_open"
    POST_CLOSE = "post_close"
    BALANCED = "balanced"
    IMBALANCED_BUYING = "imbalanced_buying"
    IMBALANCED_SELLING = "imbalanced_selling"
    ACCEPTING = "accepting"
    REJECTING = "rejecting"


class MarketPhase(Enum):
    """Market phase enumeration"""
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    SIDEWAYS = "sideways"
    MARKUP = "markup"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


@dataclass
class MacroSignal:
    """Macro market signal"""
    bias: str = "neutral"
    strength: float = 0.0
    confidence: float = 0.0
    indicators: Dict[str, float] = None

    def __post_init__(self):
        if self.indicators is None:
            self.indicators = {}


from domain.entities import ArbitrageOpportunity

class ArbitrageAnalyzer:
    """
    Advanced Arbitrage Analyzer - The sophisticated engine.
    Uses MarketContext (CVD, Wyckoff, VolProf) to score opportunities.
    """
    def __init__(self, config: Dict = None, logger: logging.Logger = None):
        self.config = config or {}
        self.logger = logger or logging.getLogger(__name__)
        self.min_confidence = Decimal(str(config.get('market_intelligence', {}).get('confidence_threshold', 0.6)))

    def score_opportunity(self, opportunity: Dict, context: MarketContext) -> Dict:
        """
        Score a potential arbitrage opportunity based on market sophisticated logic.
        Tells QBot when to be aggressive and when to be careful.
        """
        score = Decimal('1.0')
        reasoning = []

        # 1. Auction Imbalance Check
        if abs(context.auction_imbalance_score) > 0.5:
            # High imbalance against the trade direction is bad
            # If buying on buy_exchange, we want positive imbalance there
            score *= Decimal('0.8')
            reasoning.append(f"High auction imbalance: {float(context.auction_imbalance_score):.2f}")

        # 2. Wyckoff Phase Influence
        phase = context.get_wyckoff_phase()
        if "ACCUMULATION" in phase:
            score *= Decimal('1.2') # Be more aggressive during accumulation
            reasoning.append("Wyckoff Accumulation detected - aggressive mode")
        elif "MARKDOWN" in phase:
            score *= Decimal('0.5') # Be very careful during markdown
            reasoning.append("Wyckoff Markdown detected - careful mode")

        # 3. Whale Activity
        whales = context.get_whale_activity()
        if whales['detected']:
            if whales['last_whale_side'] == 'buy':
                score *= Decimal('1.1')
                reasoning.append("Whale buying detected")
            else:
                score *= Decimal('0.9')
                reasoning.append("Whale selling detected")

        # 4. Volume Profile (POC)
        vol_prof = context.get_volume_profile()
        if vol_prof['poc']:
            current_price = float(opportunity['buy_price'])
            if current_price < vol_prof['poc']:
                # Price below POC might mean mean-reversion potential
                score *= Decimal('1.05')
                reasoning.append("Price below Volume POC")

        opportunity['analysis_score'] = float(score)
        opportunity['analysis_reasoning'] = reasoning
        opportunity['is_aggressive'] = score > 1.1
        
        return opportunity


class AlphaQuadrantAnalyzer:
    """
    Quadrant Alpha Sniper (Step 4 Premium A-Bot Feature).
    
    Scores symbols by their position in a 2D quadrant:
    - X-axis: depth_ratio (bid_vol / ask_vol at 5% depth)
    - Y-axis: imbalance ((bid - ask) / (bid + ask))
    
    Symbols in the "top-right" quadrant (high depth_ratio + high imbalance)
    are prime snipe targets with 15% allocation.
    """
    
    def __init__(self, aggregator, config: Dict = None, logger: logging.Logger = None):
        """
        Args:
            aggregator: MarketData instance for metrics
            config: Bot config dict
            logger: Logger instance
        """
        self.aggregator = aggregator
        self.config = config or {}
        self.logger = logger or logging.getLogger(__name__)
        self.threshold = Decimal(str(self.config.get('ALPHA_THRESHOLD', 1.5)))
        self.allocation_pct = Decimal('0.15')  # 15% max allocation
        self.paper_mode = self.config.get('paper_mode', True)
        self.last_scan_time = 0.0
        self.scan_interval = 300  # 5 minutes default
    
    def scan(self, symbols: List[str]) -> List[Dict]:
        """
        Scan symbols for quadrant snipe opportunities.
        
        Args:
            symbols: List of trading pairs to evaluate
            
        Returns:
            List of opportunities with scores
        """
        opportunities = []
        
        if not self.aggregator:
            return opportunities
        
        # Get market means for comparison
        try:
            means = self.aggregator.get_market_means()
            mean_depth = Decimal(str(means.get('depth_ratio_mean', 1.0)))
            mean_imbalance = Decimal(str(means.get('imbalance_mean', 0.0)))
        except Exception:
            mean_depth = Decimal('1.0')
            mean_imbalance = Decimal('0.0')
        
        for symbol in symbols:
            try:
                # Get quadrant coordinates
                x = self.aggregator.get_depth_ratio(symbol)
                y = self.aggregator.get_book_imbalance(symbol)
                momentum = self.aggregator.get_price_momentum(symbol)
                
                # Convert to Decimal
                x = Decimal(str(x)) if not isinstance(x, Decimal) else x
                y = Decimal(str(y)) if not isinstance(y, Decimal) else y
                momentum = Decimal(str(momentum)) if not isinstance(momentum, Decimal) else momentum
                
                # Quadrant scoring: (x > mean AND y > mean) * (y * x * (1 + |momentum|))
                in_top_right = x > mean_depth and y > mean_imbalance
                
                if in_top_right:
                    score = y * x * (Decimal('1') + abs(momentum))
                else:
                    score = Decimal('0')
                
                if score > self.threshold:
                    opportunities.append({
                        'symbol': symbol,
                        'score': float(score),
                        'depth_ratio': float(x),
                        'imbalance': float(y),
                        'momentum': float(momentum),
                        'type': 'quadrant_alpha'
                    })
                    self.logger.info(f"[ALPHA] Snipe target: {symbol} score={float(score):.3f}")
                    
            except Exception as e:
                self.logger.debug(f"[ALPHA] Error scanning {symbol}: {e}")
                continue
        
        # Sort by score descending
        return sorted(opportunities, key=lambda x: x['score'], reverse=True)
    
    def execute_alpha_snipe(self, symbol: str, score: Decimal, available_capital: Decimal) -> Optional[Dict]:
        """
        Execute a snipe with 15% allocation and safety checks.
        
        Args:
            symbol: Trading pair to snipe
            score: Quadrant score
            available_capital: Total available capital in USD
            
        Returns:
            Execution result dict or None if blocked
        """
        # Calculate allocation
        snipe_amount = available_capital * self.allocation_pct
        
        if snipe_amount < Decimal('10'):  # Minimum trade size
            self.logger.warning(f"[ALPHA] Snipe blocked: amount too small ({snipe_amount})")
            return None
        
        if self.paper_mode:
            self.logger.info(f"[ALPHA] PAPER MODE: Would snipe {symbol} with ${snipe_amount:.2f}")
            return {
                'symbol': symbol,
                'amount': float(snipe_amount),
                'score': float(score),
                'status': 'paper_executed'
            }
        
        # Real execution would go here via order_executor
        self.logger.info(f"[ALPHA] Executing snipe: {symbol} ${snipe_amount:.2f}")
        return {
            'symbol': symbol,
            'amount': float(snipe_amount),
            'score': float(score),
            'status': 'pending_execution'
        }


class MarketContext:
    """Tracks and analyzes market context for intelligent trading."""

    def __init__(self, primary_symbol: str = None, config: Dict = None, logger: logging.Logger = None):
        """Initialize market context."""
        self.primary_symbol = primary_symbol
        self.config = config or {}
        self.logger = logger or logging.getLogger(__name__)
        self.timestamp = time.time()
        
        # Core Metrics
        self.auction_state = AuctionState.OPEN
        self.market_phase = MarketPhase.SIDEWAYS
        self.auction_imbalance_score = Decimal('0')
        self.crowd_behavior = "balanced"
        self.market_sentiment = 0.0
        self.execution_confidence = 0.5
        self.volume_strength = 0.0
        
        # Advanced Analytics History
        self.trade_history = deque(maxlen=1000) # (price, amount, side, timestamp)
        self.order_book_history = deque(maxlen=100) # (bids, asks, timestamp)
        self.cvd_history = deque(maxlen=100)
        
        # Support/Resistance
        self.key_support = None
        self.key_resistance = None
        
        self.context = {
            'volatility': 'NORMAL',
            'trend': 'NEUTRAL',
            'liquidity': 'NORMAL',
            'spread_conditions': 'NORMAL',
            'market_sentiment': 'NEUTRAL',
            'capital_mode': 'BALANCED',
            'available_capital_usd': Decimal('1000.0'),
            'exchange_balances': {}
        }

        # Analysis settings (dynamic where possible, no config ops values)
        self.latency_mode = os.getenv('LATENCY_MODE', 'laptop').lower()
        self.settings = {
            'volatility_window': 48 if self.latency_mode == 'laptop' else 24,
            'trend_window': 12 if self.latency_mode == 'laptop' else 6,
            'liquidity_threshold': Decimal('100000'),
            'spread_threshold_wide': Decimal('0.15'),
            'spread_threshold_tight': Decimal('0.05'),
            'sentiment_lookback': 24 if self.latency_mode == 'laptop' else 12,
            'whale_threshold_multiplier': 5.0 # 5x average trade size
        }
        self.volatility = Decimal('0.0')  # Current volatility for adaptive

        # Data storage
        self.price_history = {}
        self.volume_history = {}
        self.logger.info(f"Market context initialized for {primary_symbol}")

    def add_trade(self, price: Decimal, amount: Decimal, side: str):
        """Add a trade to history for advanced analytics."""
        self.trade_history.append((price, amount, side, time.time()))

    def get_whale_activity(self) -> Dict[str, Any]:
        """Detect unusually large trades relative to recent average."""
        if len(self.trade_history) < 20:
            return {'detected': False, 'score': 0.0}
        
        amounts = [float(t[1]) for t in self.trade_history]
        avg_amount = statistics.mean(amounts)
        std_amount = statistics.stdev(amounts) if len(amounts) > 1 else 0
        
        recent_trades = list(self.trade_history)[-10:]
        whales = [t for t in recent_trades if float(t[1]) > avg_amount + (self.settings['whale_threshold_multiplier'] * std_amount)]
        
        if whales:
            return {
                'detected': True,
                'count': len(whales),
                'score': min(1.0, len(whales) / 5.0),
                'last_whale_side': whales[-1][2]
            }
        return {'detected': False, 'score': 0.0}

    def get_volume_profile(self) -> Dict[str, Any]:
        """Calculate basic Volume Profile (POC, Value Area)."""
        if len(self.trade_history) < 50:
            return {'poc': None, 'va_high': None, 'va_low': None}
        
        prices = [float(t[0]) for t in self.trade_history]
        vols = [float(t[1]) for t in self.trade_history]
        
        # Bin prices into levels
        min_p, max_p = min(prices), max(prices)
        if min_p == max_p: return {'poc': min_p}
        
        bins = 20
        hist, bin_edges = np.histogram(prices, bins=bins, weights=vols)
        
        max_bin_idx = np.argmax(hist)
        poc = (bin_edges[max_bin_idx] + bin_edges[max_bin_idx+1]) / 2
        
        # Simplified Value Area (70% volume around POC)
        # In a real implementation we'd expand from POC until 70% reached
        return {
            'poc': poc,
            'va_high': poc * 1.02, # Placeholder for real VA
            'va_low': poc * 0.98
        }

    def get_wyckoff_phase(self) -> str:
        """Heuristic-based Wyckoff Phase detection."""
        # This is a complex pattern, using a simplified version based on price/vol trends
        if len(self.trade_history) < 100:
            return "UNKNOWN"
        
        prices = [float(t[0]) for t in self.trade_history]
        vols = [float(t[1]) for t in self.trade_history]
        
        # Check for Accumulation (Sideways price, increasing volume on up-moves)
        price_range = (max(prices) - min(prices)) / statistics.mean(prices)
        if price_range < 0.05:
            # Low volatility / consolidation
            up_vol = sum(vols[i] for i in range(1, len(prices)) if prices[i] > prices[i-1])
            down_vol = sum(vols[i] for i in range(1, len(prices)) if prices[i] < prices[i-1])
            if up_vol > down_vol * 1.2:
                return "PHASE_A_ACCUMULATION"
            return "PHASE_B_CONSOLIDATION"
        
        # Trend detection
        slope = np.polyfit(range(len(prices)), prices, 1)[0]
        if slope > 0: return "MARKUP"
        if slope < 0: return "MARKDOWN"
        
        return "PHASE_C_TESTING"

    def to_dict(self) -> Dict:
        """Serialize context for logging/dashboard."""
        return {
            'symbol': self.primary_symbol,
            'state': self.auction_state.value if hasattr(self.auction_state, 'value') else str(self.auction_state),
            'phase': self.market_phase.value if hasattr(self.market_phase, 'value') else str(self.market_phase),
            'imbalance': float(self.auction_imbalance_score),
            'behavior': self.crowd_behavior,
            'sentiment': self.market_sentiment,
            'confidence': self.execution_confidence,
            'wyckoff': self.get_wyckoff_phase(),
            'whale_score': self.get_whale_activity()['score']
        }

    def update(self, new_context: Dict):
        """Update market context with new information."""
        self.context.update(new_context)

        # Update capital mode if provided
        if 'capital_mode' in new_context:
            self.context['capital_mode'] = new_context['capital_mode']

        if 'available_capital_usd' in new_context:
            self.context['available_capital_usd'] = new_context['available_capital_usd']

        if 'exchange_balances' in new_context:
            self.context['exchange_balances'] = new_context['exchange_balances']

    def get_context(self) -> Dict:
        """Get current market context."""
        return self.context.copy()

    def get_spread(self, book: Dict) -> Decimal:
        """Calculate relative spread from top of book."""
        try:
            if not book or 'bids' not in book or 'asks' not in book or not book['bids'] or not book['asks']:
                return Decimal('0')
            b0, a0 = book['bids'][0], book['asks'][0]
            bid = Decimal(str(b0[0] if isinstance(b0, (list, tuple)) else b0['price']))
            ask = Decimal(str(a0[0] if isinstance(a0, (list, tuple)) else a0['price']))
            return (ask - bid) / bid if bid > 0 else Decimal('0')
        except Exception:
            return Decimal('0')

    def get_volatility(self, prices: List[Decimal]) -> Decimal:
        """Calculate standard deviation of returns."""
        try:
            if len(prices) < 2:
                return Decimal('0.0001')
            prices_f = [float(p) for p in prices]
            rets = np.diff(prices_f) / prices_f[:-1]
            return Decimal(str(max(np.std(rets), 0.0001)))
        except Exception:
            return Decimal('0.0001')

    def get_cvd(self, book: Dict) -> Decimal:
        """Calculate Cumulative Volume Delta from top levels."""
        try:
            if not book: return Decimal('0')
            bid_vol = sum(Decimal(str(l[1] if isinstance(l, (list, tuple)) else l['amount'])) for l in book.get('bids', [])[:10])
            ask_vol = sum(Decimal(str(l[1] if isinstance(l, (list, tuple)) else l['amount'])) for l in book.get('asks', [])[:10])
            return bid_vol - ask_vol
        except Exception:
            return Decimal('0')

    def get_book_imbalance(self, book: Dict) -> Decimal:
        """Calculate order book imbalance score (-1 to 1)."""
        try:
            if not book: return Decimal('0')
            bid_vol = sum(Decimal(str(l[1] if isinstance(l, (list, tuple)) else l['amount'])) for l in book.get('bids', [])[:5])
            ask_vol = sum(Decimal(str(l[1] if isinstance(l, (list, tuple)) else l['amount'])) for l in book.get('asks', [])[:5])
            return (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else Decimal('0')
        except Exception:
            return Decimal('0')

    def analyze_market(self, price_data: Dict, volume_data: Dict) -> Dict:
        """Analyze market conditions from price and volume data."""
        analysis = {}

        try:
            # Analyze volatility
            volatility = self._calculate_volatility(price_data)
            self.volatility = volatility
            analysis['volatility'] = self._classify_volatility(volatility)

            # Analyze trend
            trend = self._calculate_trend(price_data)
            analysis['trend'] = self._classify_trend(trend)

            # Analyze liquidity
            liquidity = self._calculate_liquidity(volume_data)
            analysis['liquidity'] = self._classify_liquidity(liquidity)

            # Analyze spreads (adaptive)
            spread_conditions = self._analyze_spreads(price_data)
            analysis['spread_conditions'] = spread_conditions

            # Analyze market sentiment
            sentiment = self._analyze_sentiment(price_data, volume_data)
            analysis['market_sentiment'] = sentiment

            # Update context
            self.update(analysis)

        except Exception as e:
            self.logger.error(f"Error in market analysis: {e}")
            analysis = self.context.copy()

        return analysis

    def _calculate_volatility(self, price_data: Dict) -> Decimal:
        """Calculate market volatility."""
        try:
            all_prices = []
            for symbol_data in price_data.values():
                for exchange_data in symbol_data.values():
                    if 'last' in exchange_data:
                        all_prices.append(Decimal(str(exchange_data['last'])))

            if len(all_prices) < 2:
                return Decimal('0.0')

            returns = np.diff(all_prices) / all_prices[:-1]
            volatility = np.std(returns) * np.sqrt(365 * 24)  # Annualized

            return Decimal(str(volatility))

        except Exception as e:
            self.logger.debug(f"Volatility calculation error: {e}")
            return Decimal('0.0')

    def _classify_volatility(self, volatility: float) -> str:
        """Classify volatility level."""
        if volatility > 0.8:
            return 'HIGH'
        elif volatility < 0.3:
            return 'LOW'
        else:
            return 'NORMAL'

    def _calculate_trend(self, price_data: Dict) -> Decimal:
        """Calculate market trend strength."""
        try:
            prices = []
            timestamps = []

            for symbol_data in price_data.values():
                for exchange_data in symbol_data.values():
                    if 'last' in exchange_data:
                        prices.append(Decimal(str(exchange_data['last'])))
                        if 'timestamp' in exchange_data:
                            timestamps.append(exchange_data['timestamp'])

            if len(prices) < 2:
                return Decimal('0.0')

            # Simple linear regression for trend
            if len(timestamps) == len(prices):
                x = np.array(timestamps)
                y = np.array(prices)
                slope = np.polyfit(x - x.mean(), y, 1)[0]
                trend_strength = slope / np.mean(y) if np.mean(y) > 0 else 0
            else:
                # Fallback to simple difference
                trend_strength = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0

            return Decimal(str(trend_strength))

        except Exception as e:
            self.logger.debug(f"Trend calculation error: {e}")
            return Decimal('0.0')

    def _classify_trend(self, trend_strength: float) -> str:
        """Classify market trend."""
        if trend_strength > 0.01:
            return 'BULLISH'
        elif trend_strength < -0.01:
            return 'BEARISH'
        else:
            return 'NEUTRAL'

    def _calculate_liquidity(self, order_book_data: Dict) -> Decimal:
        """Calculate market liquidity score."""
        try:
            total_bid_vol = Decimal('0')
            total_ask_vol = Decimal('0')

            for symbol_data in order_book_data.values():
                for exchange_data in symbol_data.values():
                    bid_vol = sum(Decimal(str(qty)) for _, qty in exchange_data.get('bids', [])[:10])
                    ask_vol = sum(Decimal(str(qty)) for _, qty in exchange_data.get('asks', [])[:10])
                    total_bid_vol += bid_vol
                    total_ask_vol += ask_vol

            liquidity_score = (total_bid_vol + total_ask_vol) / Decimal(
                len(order_book_data)) if order_book_data else Decimal('0.0')

            return liquidity_score

        except Exception as e:
            self.logger.debug(f"Liquidity calculation error: {e}")
            return Decimal('0.0')

    def _classify_liquidity(self, liquidity: float) -> str:
        """Classify liquidity level."""
        threshold = self.settings['liquidity_threshold']

        if liquidity > threshold * Decimal('1.5'):
            return 'HIGH'
        elif liquidity < threshold * Decimal('0.5'):
            return 'LOW'
        else:
            return 'NORMAL'

    def _analyze_spreads(self, price_data: Dict) -> str:
        """Analyze spread conditions adaptively based on volatility."""
        spreads = []
        for symbol_data in price_data.values():
            for exchange_data in symbol_data.values():
                if 'bid' in exchange_data and 'ask' in exchange_data:
                    bid = Decimal(str(exchange_data['bid']))
                    ask = Decimal(str(exchange_data['ask']))
                    spread = (ask - bid) / bid * Decimal('100') if bid > Decimal('0') else Decimal('0')
                    spreads.append(spread)

        if not spreads:
            return 'UNKNOWN'

        avg_spread = sum(spreads) / Decimal(len(spreads))

        # Adaptive thresholds based on volatility
        baseline_spread = self.volatility * Decimal('0.005')  # 0.5% of volatility
        min_spread_pct = baseline_spread
        if self.volatility > Decimal('0.8'):  # High vol
            min_spread_pct *= Decimal('1.2')  # Increase by 20%

        wide_threshold = min_spread_pct * Decimal('1.5')  # Example adaptive
        tight_threshold = min_spread_pct * Decimal('0.5')

        if avg_spread > wide_threshold:
            return 'WIDE'
        elif avg_spread < tight_threshold:
            return 'TIGHT'
        else:
            return 'NORMAL'

    def _analyze_sentiment(self, price_data: Dict, volume_data: Dict) -> str:
        """Analyze market sentiment."""
        try:
            scores = []
            for data in price_data.values():
                for ex_data in data.values():
                    scores.append(Decimal(str(ex_data.get('score', 0.0))))  # Assume sentiment score from WS/feed

            if not scores:
                return 'NEUTRAL'

            avg_score = sum(scores) / Decimal(len(scores))

            if avg_score > Decimal('0.5'):
                return 'POSITIVE'
            elif avg_score < Decimal('-0.5'):
                return 'NEGATIVE'
            else:
                return 'NEUTRAL'
        except Exception as e:
            self.logger.debug(f"Sentiment analysis error: {e}")
            return 'NEUTRAL'

    def get_trading_parameters(self) -> Dict:
        """Get recommended trading parameters based on market context."""
        params = {
            'position_size_pct': Decimal('0.5'),
            'stop_loss_pct': Decimal('0.02'),
            'take_profit_pct': Decimal('0.05'),
            'max_slippage_pct': Decimal('0.01'),
            'retry_delay': 30  # Time, skip
        }

        # Adjust based on volatility
        if self.context['volatility'] == 'HIGH':
            params['position_size_pct'] *= Decimal('0.5')
            params['stop_loss_pct'] *= Decimal('1.5')
            params['max_slippage_pct'] *= Decimal('1.5')
        elif self.context['volatility'] == 'LOW':
            params['position_size_pct'] *= Decimal('1.5')
            params['stop_loss_pct'] *= Decimal('0.8')

        # Adjust based on liquidity
        if self.context['liquidity'] == 'LOW':
            params['max_slippage_pct'] *= Decimal('2')
            params['position_size_pct'] *= Decimal('0.5')

        # Adjust based on trend
        if self.context['trend'] == 'BULLISH':
            params['take_profit_pct'] *= Decimal('1.2')
        elif self.context['trend'] == 'BEARISH':
            params['stop_loss_pct'] *= Decimal('0.8')

        # Adjust based on sentiment
        if self.context['market_sentiment'] == 'POSITIVE':
            params['position_size_pct'] *= Decimal('1.1')
        elif self.context['market_sentiment'] == 'NEGATIVE':
            params['position_size_pct'] *= Decimal('0.9')

        return params

