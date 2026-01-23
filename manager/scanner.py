# Used to be market_context.py
#risk manager & advanced arbitrage analyzer (must have only one pure function per file)
#!/usr/bin/env python3
"""
MARKET CONTEXT AND ARBITRAGE ANALYZER
Version: 2.0.0
Description: Advanced market analysis and arbitrage opportunity detection
Author: Quantum Trading Systems
"""
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
from dataclasses import dataclass
from enum import Enum
from dataclasses import dataclass
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

        # Analysis settings
        self.latency_mode = os.getenv('LATENCY_MODE', 'laptop').lower()
        self.settings = {
            'volatility_window': config.get('volatility_window', 48 if self.latency_mode == 'laptop' else 24),
            'trend_window': config.get('trend_window', 12 if self.latency_mode == 'laptop' else 6),
            'liquidity_threshold': Decimal(str(config.get('liquidity_threshold', 100000))),
            'spread_threshold_wide': Decimal(str(config.get('spread_threshold_wide', 0.15))),
            'spread_threshold_tight': Decimal(str(config.get('spread_threshold_tight', 0.05))),
            'sentiment_lookback': config.get('sentiment_lookback', 24 if self.latency_mode == 'laptop' else 12)
        }

        # Data storage
        self.price_history = {}
        self.volume_history = {}
        self.order_book_history = {}
        self.logger.info("📡 Market context initialized")

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

    def analyze_market(self, price_data: Dict, volume_data: Dict) -> Dict:
        """Analyze market conditions from price and volume data."""
        analysis = {}

        try:
            # Analyze volatility
            volatility = self._calculate_volatility(price_data)
            analysis['volatility'] = self._classify_volatility(volatility)

            # Analyze trend
            trend = self._calculate_trend(price_data)
            analysis['trend'] = self._classify_trend(trend)

            # Analyze liquidity
            liquidity = self._calculate_liquidity(volume_data)
            analysis['liquidity'] = self._classify_liquidity(liquidity)

            # Analyze spreads
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

        if liquidity > threshold * 1.5:
            return 'HIGH'
        elif liquidity < threshold * 0.5:
            return 'LOW'
        else:
            return 'NORMAL'

    def _analyze_spreads(self, price_data: Dict) -> str:
        """Analyze spread conditions."""
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

        if avg_spread > self.settings['spread_threshold_wide']:
            return 'WIDE'
        elif avg_spread < self.settings['spread_threshold_tight']:
            return 'TIGHT'
        else:
            return 'NORMAL'

    def _analyze_sentiment(self, sentiment_data: Dict) -> str:
        """Analyze market sentiment."""
        try:
            scores = []
            for data in sentiment_data.values():
                scores.append(Decimal(str(data.get('score', 0.0))))

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
            'min_confidence': Decimal(str(config.get('min_confidence', 0.6))),
            'max_slippage_percent': Decimal(str(config.get('max_slippage_percent', 0.5))),
            'liquidity_requirement': Decimal(str(config.get('liquidity_requirement', 0.1))),
            'max_position_size_usd': Decimal(str(config.get('max_position_size_usd', 5000.0))),
            'min_position_size_usd': Decimal(str(config.get('min_position_size_usd', 10.0)))
        }

        # Capital mode settings
        self.capital_mode = context.get('capital_mode', 'BALANCED')
        self.available_capital_usd = Decimal(str(context.get('available_capital_usd', 1000.0)))
        self.exchange_balances = context.get('exchange_balances', {})
        
        self.logger.info("✅ Arbitrage analyzer initialized")

    def analyze_opportunity(self, opportunity: Dict, book: Dict, prices: List[Decimal]) -> Dict:
        spread = self.context.get_spread(book)
        volatility = self.context.get_volatility(prices)
        cvd = self.context.get_cvd(book)
        imbalance = self.context.get_book_imbalance(book)
        score = spread * (Decimal('1') / volatility) * (cvd / Decimal('1000')) * imbalance
        return {'spread': spread, 'volatility': volatility, 'cvd': cvd, 'imbalance': imbalance, 'score': score}

    def find_opportunities(self, price_data: Dict, symbols: List[str]) -> List[ArbitrageOpportunity]:
        """Find arbitrage opportunities across exchanges and symbols."""
        opportunities = []
        
        if not price_data:
            return opportunities
        
        # Get trading parameters adjusted for current context
        trading_params = self._get_trading_parameters()
        
        for symbol in symbols:
            if symbol not in price_data:
                continue
            
            symbol_opportunities = self._analyze_symbol(
                symbol, price_data[symbol], trading_params
            )
            opportunities.extend(symbol_opportunities)
        
        # Sort by estimated profit
        opportunities.sort(key=lambda x: x.estimated_profit, reverse=True)
        
        return opportunities[:10]  # Return top 10 opportunities

    def get_trading_parameters(self) -> Dict:
        params = {
            'position_size_pct': Decimal('0.5'),
            'stop_loss_pct': Decimal('0.02'),
            'take_profit_pct': Decimal('0.05'),
            'max_slippage_pct': Decimal('0.01'),
            'retry_delay': 30  # seconds, not money
        }

        if self.context['volatility'] == 'HIGH':
            params['position_size_pct'] *= Decimal('0.5')
            params['stop_loss_pct'] *= Decimal('1.5')
            params['max_slippage_pct'] *= Decimal('1.5')
        elif self.context['volatility'] == 'LOW':
            params['position_size_pct'] *= Decimal('1.5')
            params['stop_loss_pct'] *= Decimal('0.8')

        if self.context['liquidity'] == 'LOW':
            params['max_slippage_pct'] *= Decimal('2')
            params['position_size_pct'] *= Decimal('0.5')

        if self.context['trend'] == 'BULLISH':
            params['take_profit_pct'] *= Decimal('1.2')
        elif self.context['trend'] == 'BEARISH':
            params['stop_loss_pct'] *= Decimal('0.8')

        if self.context['market_sentiment'] == 'POSITIVE':
            params['position_size_pct'] *= Decimal('1.1')
        elif self.context['market_sentiment'] == 'NEGATIVE':
            params['position_size_pct'] *= Decimal('0.9')

        return params

    def _calculate_dynamic_position_size(self) -> Decimal:
        """Calculate dynamic position size based on capital mode and available capital."""
        try:
            # Base calculation from available capital
            if self.capital_mode == 'BOTTLENECKED':
                # In bottleneck mode, use 95% of available capital (capped)
                base_size = self.available_capital_usd * Decimal('0.95')
            else:
                # BALANCED mode
                # In balanced mode, use 40% of available capital
                base_size = self.available_capital_usd * Decimal('0.40')

            # Apply config limits
            position_size = min(base_size, self.settings['max_position_size_usd'])
            position_size = max(position_size, self.settings['min_position_size_usd'])

            # Ensure we don't exceed individual exchange balances
            if self.exchange_balances:
                min_balance = min(self.exchange_balances.values())
                position_size = min(position_size, min_balance * Decimal('0.8'))  # 80% safety margin

            self.logger.debug(
                f" Dynamic position size: ${position_size.quantize(Decimal('0.00'))} "
                f"(Mode: {self.capital_mode}, Available: ${self.available_capital_usd.quantize(Decimal('0.00'))})"
            )
            return position_size
        except Exception as e:
            self.logger.error(f"Error calculating dynamic position size: {e}")
            # Fallback to config default
            return Decimal(str(self.config.get('position_size', 1000.0)))

    def _analyze_symbol(self, symbol: str, symbol_data: Dict, trading_params: Dict) -> List[ArbitrageOpportunity]:
        """Analyze arbitrage opportunities for a single symbol."""
        opportunities = []
        exchanges = list(symbol_data.keys())
        
        if len(exchanges) < 2:
            return opportunities
        
        # Get dynamic position size for this analysis
        position_size_usd = trading_params['position_size_usd']
        base_currency = symbol.split('/')[0]
        
        # Compare all exchange pairs
        for i, buy_exchange in enumerate(exchanges):
            for j, sell_exchange in enumerate(exchanges):
                if i == j:
                    continue
                
                buy_data = symbol_data.get(buy_exchange)
                sell_data = symbol_data.get(sell_exchange)
                
                if not buy_data or not sell_data:
                    continue
                
                # Extract prices
                buy_price = buy_data.get('ask')
                sell_price = sell_data.get('bid')
                
                if not buy_price or not sell_price or buy_price <= 0 or sell_price <= 0:
                    continue
                
                # Calculate spread
                spread_pct = (sell_price - buy_price) / buy_price * 100
                
                # Check minimum spread
                if spread_pct < trading_params['min_spread']:
                    continue
                
                # Calculate estimated profit with dynamic position size
                asset_amount = position_size_usd / buy_price
                
                # Account for fees
                buy_fee_rate = 0.001  # Would come from exchange wrapper
                sell_fee_rate = 0.001  # Would come from exchange wrapper
                
                gross_profit = (sell_price - buy_price) * asset_amount
                fees = (buy_price * buy_fee_rate + sell_price * sell_fee_rate) * asset_amount
                estimated_profit = gross_profit - fees
                
                # Check minimum profit
                if estimated_profit < trading_params['min_profit_usd']:
                    continue
                
                # Calculate confidence
                confidence = self._calculate_confidence(
                    buy_data, sell_data, spread_pct, asset_amount
                )
                
                # Adjust confidence for capital mode
                if self.capital_mode == 'BOTTLENECKED':
                    confidence *= 0.9  # Slightly less confident in bottleneck
                elif self.capital_mode == 'BALANCED':
                    confidence *= 1.1  # More confident in balanced mode
                
                # Check minimum confidence
                if confidence < self.settings['min_confidence']:
                    continue
                
                # Check liquidity
                if not self._check_liquidity(buy_data, sell_data, asset_amount):
                    continue
                
                # Create opportunity
                opportunity = ArbitrageOpportunity(
                    symbol=symbol,
                    buy_exchange=buy_exchange,
                    sell_exchange=sell_exchange,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    spread_percentage=spread_pct,
                    estimated_profit=estimated_profit,
                    confidence=confidence,
                    timestamp=time.time(),
                    capital_mode=self.capital_mode,
                    position_size_usd=position_size_usd
                )
                
                opportunities.append(opportunity)
        
        return opportunities

    def _calculate_confidence(self, buy_data: Dict, sell_data: Dict, spread_pct: Decimal, asset_amount: Decimal) -> Decimal:
        """Calculate confidence score for an opportunity."""
        confidence = Decimal('0.5')  # Base confidence

        # Spread-based confidence
        if spread_pct > Decimal('0.15'):
            confidence += Decimal('0.2')
        elif spread_pct > Decimal('0.10'):
            confidence += Decimal('0.1')

        # Volume-based confidence
        buy_volume = Decimal(str(buy_data.get('volume', 0)))
        sell_volume = Decimal(str(sell_data.get('volume', 0)))

        if buy_volume > Decimal('100') and sell_volume > Decimal('100'):
            confidence += Decimal('0.1')
        elif buy_volume > Decimal('50') and sell_volume > Decimal('50'):
            confidence += Decimal('0.05')

        # Order book depth confidence
        buy_depth = self._calculate_order_book_depth(buy_data.get('order_book', {}))
        sell_depth = self._calculate_order_book_depth(sell_data.get('order_book', {}))

        if buy_depth > asset_amount * Decimal('2') and sell_depth > asset_amount * Decimal('2'):
            confidence += Decimal('0.15')
        elif buy_depth > asset_amount and sell_depth > asset_amount:
            confidence += Decimal('0.05')

        # Cap confidence between 0.1 and 0.95
        return max(Decimal('0.1'), min(Decimal('0.95'), confidence))

    def _calculate_order_book_depth(self, order_book: Dict) -> Decimal:
        """Calculate order book depth."""
        if not order_book or 'bids' not in order_book or 'asks' not in order_book:
            return Decimal('0.0')

        bids = order_book.get('bids', [])
        asks = order_book.get('asks', [])

        if not bids or not asks:
            return Decimal('0.0')

        # Calculate depth up to 1% from best price
        best_bid = Decimal(str(bids[0][0]))
        best_ask = Decimal(str(asks[0][0]))
        mid_price = (best_bid + best_ask) / Decimal('2')

        depth_range = mid_price * Decimal('0.01')  # 1% range

        bid_depth = sum(Decimal(str(amount)) for price, amount in bids if Decimal(str(price)) >= best_bid - depth_range)
        ask_depth = sum(Decimal(str(amount)) for price, amount in asks if Decimal(str(price)) <= best_ask + depth_range)

        return min(bid_depth, ask_depth)

    def _check_liquidity(self, buy_data: Dict, sell_data: Dict, required_amount: Decimal) -> bool:
        """Check if there's sufficient liquidity for the trade."""
        buy_order_book = buy_data.get('order_book', {})
        sell_order_book = sell_data.get('order_book', {})

        # Check buy side (asks)
        buy_liquidity = Decimal('0.0')
        if 'asks' in buy_order_book:
            for price, amount in buy_order_book['asks']:
                buy_liquidity += Decimal(str(amount))
                if buy_liquidity >= required_amount:
                    break

        # Check sell side (bids)
        sell_liquidity = Decimal('0.0')
        if 'bids' in sell_order_book:
            for price, amount in sell_order_book['bids']:
                sell_liquidity += Decimal(str(amount))
                if sell_liquidity >= required_amount:
                    break

        return buy_liquidity >= required_amount and sell_liquidity >= required_amount

    def filter_opportunities(self, opportunities: List[ArbitrageOpportunity], max_opportunities: int = 5) -> List[ArbitrageOpportunity]:
        """Filter and rank opportunities."""
        if not opportunities:
            return []
        
        # Filter by minimum confidence
        filtered = [opp for opp in opportunities 
                   if opp.confidence >= self.settings['min_confidence']]
        
        if not filtered:
            return []
        
        # Score opportunities
        scored = []
        for opp in filtered:
            score = self._score_opportunity(opp)
            scored.append((score, opp))
        
        # Sort by score
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Return top opportunities
        return [opp for _, opp in scored[:max_opportunities]]

    def _score_opportunity(self, opportunity: ArbitrageOpportunity) -> Decimal:
        """Score an opportunity for ranking."""
        score = Decimal('0.0')

        # Profit score (40%)
        profit_score = min(opportunity.estimated_profit / Decimal('10'), Decimal('1.0')) * Decimal('40')
        score += profit_score

        # Confidence score (30%)
        confidence_score = opportunity.confidence * Decimal('30')
        score += confidence_score

        # Spread score (20%)
        spread_score = min(opportunity.spread_percentage / Decimal('0.3'), Decimal('1.0')) * Decimal('20')
        score += spread_score

        # Capital mode bonus (10%)
        if opportunity.capital_mode == 'BALANCED':
            score += Decimal('10')  # Bonus for balanced mode
        elif opportunity.capital_mode == 'BOTTLENECKED':
            score += Decimal('5')  # Smaller bonus for bottleneck mode

        return score