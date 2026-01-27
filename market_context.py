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
from typing import Dict, List, Optional, Any


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


class ArbitrageAnalyzer:
    """
    Simple arbitrage analyzer placeholder
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.opportunities: List[Dict] = []
    
    def analyze_opportunities(self, prices: Dict[str, Dict[str, float]], 
                            order_books: Dict[str, Dict[str, Any]],
                            fees: Dict[str, float]) -> List[Dict[str, Any]]:
        """Analyze arbitrage opportunities"""
        # Return empty list for now - actual implementation would go here
        return []
    
    def get_best_opportunity(self) -> Optional[Dict[str, Any]]:
        """Get best arbitrage opportunity"""
        return None
    

@dataclass
class ArbitrageOpportunity:
    """Represents an arbitrage opportunity."""
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_percentage: float
    estimated_profit: float
    confidence: float
    timestamp: float
    capital_mode: str = "BALANCED"
    position_size_usd: float = 1000.0


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
            'available_capital_usd': 1000.0,
            'exchange_balances': {}
        }
        
        # Analysis settings
        self.settings = {
            'volatility_window': config.get('volatility_window', 24),
            'trend_window': config.get('trend_window', 6),
            'liquidity_threshold': config.get('liquidity_threshold', 100000),
            'spread_threshold_wide': config.get('spread_threshold_wide', 0.15),
            'spread_threshold_tight': config.get('spread_threshold_tight', 0.05),
            'sentiment_lookback': config.get('sentiment_lookback', 12)
        }
        
        # Data storage
        self.price_history = {}
        self.volume_history = {}
        self.order_book_history = {}
        
        self.logger.info("✅ Market context initialized")
    
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
    
    def _calculate_volatility(self, price_data: Dict) -> float:
        """Calculate market volatility."""
        try:
            all_prices = []
            for symbol_data in price_data.values():
                for exchange_data in symbol_data.values():
                    if 'last' in exchange_data:
                        all_prices.append(exchange_data['last'])
            
            if len(all_prices) < 2:
                return 0.0
            
            returns = np.diff(all_prices) / all_prices[:-1]
            volatility = np.std(returns) * np.sqrt(365 * 24)  # Annualized
            
            return float(volatility)
            
        except Exception as e:
            self.logger.debug(f"Volatility calculation error: {e}")
            return 0.0
    
    def _classify_volatility(self, volatility: float) -> str:
        """Classify volatility level."""
        if volatility > 0.8:
            return 'HIGH'
        elif volatility < 0.3:
            return 'LOW'
        else:
            return 'NORMAL'
    
    def _calculate_trend(self, price_data: Dict) -> float:
        """Calculate market trend strength."""
        try:
            prices = []
            timestamps = []
            
            for symbol_data in price_data.values():
                for exchange_data in symbol_data.values():
                    if 'last' in exchange_data:
                        prices.append(exchange_data['last'])
                        if 'timestamp' in exchange_data:
                            timestamps.append(exchange_data['timestamp'])
            
            if len(prices) < 2:
                return 0.0
            
            # Simple linear regression for trend
            if len(timestamps) == len(prices):
                x = np.array(timestamps)
                y = np.array(prices)
                slope = np.polyfit(x - x.mean(), y, 1)[0]
                trend_strength = slope / np.mean(y) if np.mean(y) > 0 else 0
            else:
                # Fallback to simple difference
                trend_strength = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
            
            return float(trend_strength)
            
        except Exception as e:
            self.logger.debug(f"Trend calculation error: {e}")
            return 0.0
    
    def _classify_trend(self, trend_strength: float) -> str:
        """Classify market trend."""
        if trend_strength > 0.01:
            return 'BULLISH'
        elif trend_strength < -0.01:
            return 'BEARISH'
        else:
            return 'NEUTRAL'
    
    def _calculate_liquidity(self, volume_data: Dict) -> float:
        """Calculate market liquidity."""
        try:
            total_volume = 0.0
            count = 0
            
            for symbol_data in volume_data.values():
                for exchange_data in symbol_data.values():
                    if 'volume' in exchange_data:
                        total_volume += exchange_data['volume']
                        count += 1
            
            if count == 0:
                return 0.0
            
            return total_volume / count
            
        except Exception as e:
            self.logger.debug(f"Liquidity calculation error: {e}")
            return 0.0
    
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
        """Analyze market spread conditions."""
        try:
            spreads = []
            
            for symbol, symbol_data in price_data.items():
                for exchange_id, data in symbol_data.items():
                    if 'ask' in data and 'bid' in data and data['ask'] > 0:
                        spread = (data['ask'] - data['bid']) / data['ask'] * 100
                        spreads.append(spread)
            
            if not spreads:
                return 'NORMAL'
            
            avg_spread = np.mean(spreads)
            
            if avg_spread > self.settings['spread_threshold_wide']:
                return 'WIDE'
            elif avg_spread < self.settings['spread_threshold_tight']:
                return 'TIGHT'
            else:
                return 'NORMAL'
                
        except Exception as e:
            self.logger.debug(f"Spread analysis error: {e}")
            return 'NORMAL'
    
    def _analyze_sentiment(self, price_data: Dict, volume_data: Dict) -> str:
        """Analyze market sentiment."""
        try:
            # Simple sentiment based on price movement and volume
            price_changes = []
            volume_changes = []
            
            for symbol in price_data:
                if symbol in volume_data:
                    price_symbol_data = price_data[symbol]
                    volume_symbol_data = volume_data[symbol]
                    
                    for exchange_id in price_symbol_data:
                        if exchange_id in volume_symbol_data:
                            price_data_point = price_symbol_data[exchange_id]
                            volume_data_point = volume_symbol_data[exchange_id]
                            
                            if 'last' in price_data_point and 'volume' in volume_data_point:
                                # This is simplified - real implementation would track over time
                                price_changes.append(price_data_point['last'])
                                volume_changes.append(volume_data_point['volume'])
            
            if len(price_changes) < 2 or len(volume_changes) < 2:
                return 'NEUTRAL'
            
            # Very basic sentiment heuristic
            avg_price_change = np.mean(np.diff(price_changes) / price_changes[:-1])
            avg_volume_change = np.mean(np.diff(volume_changes) / volume_changes[:-1])
            
            if avg_price_change > 0.001 and avg_volume_change > 0:
                return 'BULLISH'
            elif avg_price_change < -0.001 and avg_volume_change > 0:
                return 'BEARISH'
            else:
                return 'NEUTRAL'
                
        except Exception as e:
            self.logger.debug(f"Sentiment analysis error: {e}")
            return 'NEUTRAL'
    
    def get_trading_parameters(self, context: Dict) -> Dict:
        """Get trading parameters adjusted for current market context."""
        params = {
            'min_profit_threshold': self.config.get('min_profit_threshold', 0.5),
            'min_spread_percentage': 0.08,
            'confidence_multiplier': 1.0,
            'position_size_multiplier': 1.0
        }
        
        # Adjust for volatility
        volatility = context.get('volatility', 'NORMAL')
        if volatility == 'HIGH':
            params['min_profit_threshold'] *= 1.5
            params['min_spread_percentage'] *= 1.3
            params['confidence_multiplier'] *= 0.7
            params['position_size_multiplier'] *= 0.5
        elif volatility == 'LOW':
            params['min_profit_threshold'] *= 0.8
            params['min_spread_percentage'] *= 0.8
            params['confidence_multiplier'] *= 1.2
            params['position_size_multiplier'] *= 1.2
        
        # Adjust for spread conditions
        spread_conditions = context.get('spread_conditions', 'NORMAL')
        if spread_conditions == 'WIDE':
            params['min_spread_percentage'] *= 1.2
            params['confidence_multiplier'] *= 0.9
        elif spread_conditions == 'TIGHT':
            params['min_spread_percentage'] *= 0.8
            params['confidence_multiplier'] *= 1.1
        
        # Adjust for market sentiment
        sentiment = context.get('market_sentiment', 'NEUTRAL')
        if sentiment == 'BEARISH':
            params['confidence_multiplier'] *= 0.9
        elif sentiment == 'BULLISH':
            params['confidence_multiplier'] *= 1.1
        
        # Adjust for capital mode
        capital_mode = context.get('capital_mode', 'BALANCED')
        if capital_mode == 'BOTTLENECKED':
            # Be more conservative in bottleneck mode
            params['confidence_multiplier'] *= 0.8
            params['position_size_multiplier'] *= 0.7
        elif capital_mode == 'BALANCED':
            # Can be more aggressive in balanced mode
            params['confidence_multiplier'] *= 1.1
        
        return params


class ArbitrageAnalyzer:
    """Advanced arbitrage opportunity analyzer."""
    
    def __init__(self, context: Dict, config: Dict, logger: logging.Logger):
        """Initialize arbitrage analyzer."""
        self.context = context
        self.config = config
        self.logger = logger
        
        # Analysis settings
        self.settings = {
            'min_confidence': config.get('min_confidence', 0.6),
            'max_slippage_percent': config.get('max_slippage_percent', 0.5),
            'liquidity_requirement': config.get('liquidity_requirement', 0.1),
            'max_position_size_usd': config.get('max_position_size_usd', 5000.0),
            'min_position_size_usd': config.get('min_position_size_usd', 10.0)
        }
        
        # Capital mode settings
        self.capital_mode = context.get('capital_mode', 'BALANCED')
        self.available_capital_usd = context.get('available_capital_usd', 1000.0)
        self.exchange_balances = context.get('exchange_balances', {})
        
        self.logger.info("✅ Arbitrage analyzer initialized")
    
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
    
    def _get_trading_parameters(self) -> Dict:
        """Get trading parameters adjusted for capital mode."""
        params = {
            'min_spread': 0.08,  # 0.08% minimum spread
            'min_profit_usd': self.config.get('min_profit_threshold', 0.5),
            'confidence_base': 0.5,
            'position_size_usd': self._calculate_dynamic_position_size()
        }
        
        # Adjust for capital mode
        if self.capital_mode == 'BOTTLENECKED':
            # More conservative in bottleneck mode
            params['min_spread'] *= 1.2
            params['min_profit_usd'] *= 1.3
            params['confidence_base'] *= 0.8
        elif self.capital_mode == 'BALANCED':
            # Can be more aggressive in balanced mode
            params['min_spread'] *= 0.9
            params['confidence_base'] *= 1.1
        
        return params
    
    def _calculate_dynamic_position_size(self) -> float:
        """Calculate dynamic position size based on capital mode and available capital."""
        try:
            # Base calculation from available capital
            if self.capital_mode == 'BOTTLENECKED':
                # In bottleneck mode, use 95% of available capital (capped)
                base_size = self.available_capital_usd * 0.95
            else:  # BALANCED mode
                # In balanced mode, use 40% of available capital
                base_size = self.available_capital_usd * 0.40
            
            # Apply config limits
            position_size = min(base_size, self.settings['max_position_size_usd'])
            position_size = max(position_size, self.settings['min_position_size_usd'])
            
            # Ensure we don't exceed individual exchange balances
            if self.exchange_balances:
                min_balance = min(self.exchange_balances.values())
                position_size = min(position_size, min_balance * 0.8)  # 80% safety margin
            
            self.logger.debug(
                f"   Dynamic position size: ${position_size:.2f} "
                f"(Mode: {self.capital_mode}, Available: ${self.available_capital_usd:.2f})"
            )
            
            return position_size
            
        except Exception as e:
            self.logger.error(f"Error calculating dynamic position size: {e}")
            # Fallback to config default
            return self.config.get('position_size', 1000.0)
    
    def _analyze_symbol(self, symbol: str, symbol_data: Dict, 
                       trading_params: Dict) -> List[ArbitrageOpportunity]:
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
    
    def _calculate_confidence(self, buy_data: Dict, sell_data: Dict, 
                            spread_pct: float, asset_amount: float) -> float:
        """Calculate confidence score for an opportunity."""
        confidence = 0.5  # Base confidence
        
        # Spread-based confidence
        if spread_pct > 0.15:
            confidence += 0.2
        elif spread_pct > 0.10:
            confidence += 0.1
        
        # Volume-based confidence
        buy_volume = buy_data.get('volume', 0)
        sell_volume = sell_data.get('volume', 0)
        
        if buy_volume > 100 and sell_volume > 100:
            confidence += 0.1
        elif buy_volume > 50 and sell_volume > 50:
            confidence += 0.05
        
        # Order book depth confidence
        buy_depth = self._calculate_order_book_depth(buy_data.get('order_book', {}))
        sell_depth = self._calculate_order_book_depth(sell_data.get('order_book', {}))
        
        if buy_depth > asset_amount * 2 and sell_depth > asset_amount * 2:
            confidence += 0.15
        elif buy_depth > asset_amount and sell_depth > asset_amount:
            confidence += 0.05
        
        # Cap confidence between 0.1 and 0.95
        return max(0.1, min(0.95, confidence))
    
    def _calculate_order_book_depth(self, order_book: Dict) -> float:
        """Calculate order book depth."""
        if not order_book or 'bids' not in order_book or 'asks' not in order_book:
            return 0.0
        
        bids = order_book.get('bids', [])
        asks = order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0
        
        # Calculate depth up to 1% from best price
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid_price = (best_bid + best_ask) / 2
        
        depth_range = mid_price * 0.01  # 1% range
        
        bid_depth = sum(amount for price, amount in bids if price >= best_bid - depth_range)
        ask_depth = sum(amount for price, amount in asks if price <= best_ask + depth_range)
        
        return min(bid_depth, ask_depth)
    
    def _check_liquidity(self, buy_data: Dict, sell_data: Dict, 
                        required_amount: float) -> bool:
        """Check if there's sufficient liquidity for the trade."""
        buy_order_book = buy_data.get('order_book', {})
        sell_order_book = sell_data.get('order_book', {})
        
        # Check buy side (asks)
        buy_liquidity = 0.0
        if 'asks' in buy_order_book:
            for price, amount in buy_order_book['asks']:
                buy_liquidity += amount
                if buy_liquidity >= required_amount:
                    break
        
        # Check sell side (bids)
        sell_liquidity = 0.0
        if 'bids' in sell_order_book:
            for price, amount in sell_order_book['bids']:
                sell_liquidity += amount
                if sell_liquidity >= required_amount:
                    break
        
        return buy_liquidity >= required_amount and sell_liquidity >= required_amount
    
    def filter_opportunities(self, opportunities: List[ArbitrageOpportunity],
                           max_opportunities: int = 5) -> List[ArbitrageOpportunity]:
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
    
    def _score_opportunity(self, opportunity: ArbitrageOpportunity) -> float:
        """Score an opportunity for ranking."""
        score = 0.0
        
        # Profit score (40%)
        profit_score = min(opportunity.estimated_profit / 10, 1.0) * 40
        score += profit_score
        
        # Confidence score (30%)
        confidence_score = opportunity.confidence * 30
        score += confidence_score
        
        # Spread score (20%)
        spread_score = min(opportunity.spread_percentage / 0.3, 1.0) * 20
        score += spread_score
        
        # Capital mode bonus (10%)
        if opportunity.capital_mode == 'BALANCED':
            score += 10  # Bonus for balanced mode
        elif opportunity.capital_mode == 'BOTTLENECKED':
            score += 5   # Smaller bonus for bottleneck mode
        
        return score
