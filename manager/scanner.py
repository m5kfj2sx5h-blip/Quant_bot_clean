import logging
import time
from typing import Dict, List, Optional, Tuple, Any
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


class MarketPhase(Enum):
    """Market phase enumeration"""
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    SIDEWAYS = "sideways"


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


class MarketContext:
    """Tracks and analyzes market context for intelligent trading."""

    def __init__(self, config: Dict, logger: logging.Logger):
        """Initialize market context."""
        self.config = config
        self.logger = logger
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
            'sentiment_lookback': 24 if self.latency_mode == 'laptop' else 12
        }
        self.volatility = Decimal('0.0')  # Current volatility for adaptive

        # Data storage
        self.price_history = {}
        self.volume_history = {}
        self.order_book_history = {}
        self.logger.info("Market context initialized")

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


@dataclass
class ArbitrageOpportunity:
    """Represents an arbitrage opportunity."""
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: Decimal
    sell_price: Decimal
    spread_percentage: Decimal
    estimated_profit: Decimal
    confidence: Decimal
    timestamp: float  # Time, keep float
    capital_mode: str = "BALANCED"
    position_size_usd: Decimal = Decimal('1000.0')


class ArbitrageAnalyzer:
    """Advanced arbitrage opportunity analyzer."""

    def __init__(self, context: Dict, config: Dict, logger: logging.Logger):
        """Initialize arbitrage analyzer."""
        self.context = context
        self.config = config
        self.logger = logger

        # Analysis settings
        self.settings = {
            'min_confidence': Decimal('0.6'),
            'max_slippage_percent': Decimal('0.5'),
            'liquidity_requirement': Decimal('0.1'),
            'max_position_size_usd': Decimal('5000.0'),
            'min_position_size_usd': Decimal('10.0')
        }

        # Capital mode settings
        self.capital_mode = context.get('capital_mode', 'BALANCED')
        self.available_capital_usd = Decimal(str(context.get('available_capital_usd', 1000.0)))
        self.exchange_balances = context.get('exchange_balances', {})

        self.logger.info("Arbitrage analyzer initialized")

    def analyze_opportunity(self, opportunity: Dict, book: Dict, prices: List[Decimal]) -> Dict:
        spread = self.context.get_spread(book)
        volatility = self.context.get_volatility(prices)
        cvd = self.context.get_cvd(book)
        imbalance = self.context.get_book_imbalance(book)
        score = spread * (Decimal('1') / volatility) * (cvd / Decimal('1000')) * imbalance
        return {'spread': spread, 'volatility': volatility, 'cvd': cvd, 'imbalance': imbalance, 'score': score}