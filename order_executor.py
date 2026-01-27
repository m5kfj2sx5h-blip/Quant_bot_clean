#!/usr/bin/env python3
"""
ORDER EXECUTION ENGINE
Version: 2.0.0
Description: Advanced order execution with intelligent routing and risk management
Author: Quantum Trading Systems
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal, ROUND_DOWN

from exchange_wrappers import ExchangeWrapper


class OrderExecutor:
    """Advanced order executor with intelligent routing and risk management."""
    
    def __init__(self, config: Dict, logger: logging.Logger):
        """Initialize the order executor."""
        self.config = config
        self.logger = logger
        self.execution_history = []
        self.max_history_size = 100
        
        # Execution settings
        self.settings = {
            'max_slippage_percent': config.get('max_slippage_percent', 0.5),
            'max_retries': config.get('max_retries', 3),
            'retry_delay': config.get('retry_delay', 1.0),
            'timeout_seconds': config.get('timeout_seconds', 30),
            'enable_hedging': config.get('enable_hedging', False),
            'hedge_threshold_usd': config.get('hedge_threshold_usd', 1000)
        }
        
        # Performance tracking
        self.total_trades = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        
        self.logger.info("✅ Order executor initialized")
    
    def execute_arbitrage(self, buy_exchange: str, sell_exchange: str,
                         buy_price: float, sell_price: float,
                         symbol: str, position_size: float,
                         expected_profit: float, 
                         trade_params: Optional[Dict] = None) -> bool:
        """
        Execute an arbitrage trade with dynamic position sizing.
        
        Args:
            buy_exchange: Exchange to buy from
            sell_exchange: Exchange to sell to
            buy_price: Buy price estimate
            sell_price: Sell price estimate
            symbol: Trading symbol (e.g., 'BTC/USDT')
            position_size: Dynamic position size in USD (passed from orchestrator)
            expected_profit: Expected profit in USD
            trade_params: Additional trade parameters including capital_mode
        
        Returns:
            bool: True if execution was successful
        """
        start_time = time.time()
        self.logger.info(f"🚀 Executing arbitrage trade: {symbol}")
        
        # Extract trade parameters
        if trade_params is None:
            trade_params = {}
        
        capital_mode = trade_params.get('capital_mode', 'BALANCED')
        dynamic_position_size = trade_params.get('dynamic_position_size', position_size)
        
        # Log dynamic sizing information
        self.logger.info(
            f"🎯 Capital Mode: {capital_mode} | "
            f"Dynamic Position Size: ${dynamic_position_size:.2f} | "
            f"Expected Profit: ${expected_profit:.2f}"
        )
        
        # Convert USD position size to asset amount
        base_currency = symbol.split('/')[0]
        asset_amount = self._calculate_asset_amount(dynamic_position_size, buy_price, base_currency)
        
        if asset_amount <= 0:
            self.logger.error(f"❌ Invalid asset amount: {asset_amount}")
            return False
        
        # Validate execution parameters
        if not self._validate_execution_params(buy_exchange, sell_exchange, 
                                             buy_price, sell_price, symbol, 
                                             asset_amount, expected_profit):
            return False
        
        # Calculate acceptable price ranges with slippage tolerance
        max_buy_price = buy_price * (1 + self.settings['max_slippage_percent'] / 100)
        min_sell_price = sell_price * (1 - self.settings['max_slippage_percent'] / 100)
        
        # Execute buy order
        self.logger.info(f"🛒 Buying {asset_amount:.6f} {base_currency} on {buy_exchange}")
        buy_result = self._execute_order(
            exchange_id=buy_exchange,
            symbol=symbol,
            side='buy',
            amount=asset_amount,
            price_limit=max_buy_price,
            order_type='limit'
        )
        
        if not buy_result['success']:
            self.logger.error(f"❌ Buy order failed: {buy_result.get('error', 'Unknown error')}")
            self.failed_trades += 1
            return False
        
        actual_buy_price = buy_result['price']
        actual_buy_amount = buy_result['amount']
        buy_fee = buy_result.get('fee', 0.0)
        
        # Execute sell order
        self.logger.info(f"💰 Selling {actual_buy_amount:.6f} {base_currency} on {sell_exchange}")
        sell_result = self._execute_order(
            exchange_id=sell_exchange,
            symbol=symbol,
            side='sell',
            amount=actual_buy_amount,
            price_limit=min_sell_price,
            order_type='limit'
        )
        
        if not sell_result['success']:
            self.logger.error(f"❌ Sell order failed: {sell_result.get('error', 'Unknown error')}")
            
            # If hedging is enabled and we're stuck with inventory
            if self.settings['enable_hedging']:
                self._hedge_position(buy_exchange, sell_exchange, symbol, actual_buy_amount, actual_buy_price)
            
            self.failed_trades += 1
            return False
        
        actual_sell_price = sell_result['price']
        sell_fee = sell_result.get('fee', 0.0)
        
        # Calculate actual profit/loss
        gross_profit = (actual_sell_price - actual_buy_price) * actual_buy_amount
        total_fees = buy_fee + sell_fee
        net_profit = gross_profit - total_fees
        
        # Record trade execution
        execution_time = time.time() - start_time
        trade_record = {
            'timestamp': time.time(),
            'buy_exchange': buy_exchange,
            'sell_exchange': sell_exchange,
            'symbol': symbol,
            'buy_price': actual_buy_price,
            'sell_price': actual_sell_price,
            'amount': actual_buy_amount,
            'gross_profit': gross_profit,
            'fees': total_fees,
            'net_profit': net_profit,
            'expected_profit': expected_profit,
            'execution_time': execution_time,
            'capital_mode': capital_mode,
            'position_size_usd': dynamic_position_size,
            'success': True
        }
        
        # Update performance metrics
        self.total_trades += 1
        self.successful_trades += 1
        
        if net_profit > 0:
            self.total_profit += net_profit
            profit_status = "PROFIT"
        else:
            self.total_loss += abs(net_profit)
            profit_status = "LOSS"
        
        # Add to history
        self.execution_history.append(trade_record)
        if len(self.execution_history) > self.max_history_size:
            self.execution_history.pop(0)
        
        # Log trade summary
        self.logger.info(f"""
        ✅ ARBITRAGE EXECUTION COMPLETE
        ═══════════════════════════════════════
        Symbol:           {symbol}
        Capital Mode:     {capital_mode}
        Position Size:    ${dynamic_position_size:.2f} → {actual_buy_amount:.6f} {base_currency}
        Buy Exchange:     {buy_exchange} @ ${actual_buy_price:.2f}
        Sell Exchange:    {sell_exchange} @ ${actual_sell_price:.2f}
        Spread:           {(actual_sell_price - actual_buy_price) / actual_buy_price * 100:.3f}%
        ───────────────────────────────────────
        Gross Profit:     ${gross_profit:.4f}
        Fees:             ${total_fees:.4f}
        Net Profit:       ${net_profit:.4f}
        Expected Profit:  ${expected_profit:.4f}
        Execution Time:   {execution_time:.2f}s
        Result:           {profit_status}
        ═══════════════════════════════════════
        """)
        
        return True
    
    def _calculate_asset_amount(self, position_size_usd: float, 
                               price: float, base_currency: str) -> float:
        """Calculate asset amount from USD position size."""
        if price <= 0:
            self.logger.error(f"❌ Invalid price for amount calculation: {price}")
            return 0.0
        
        amount = position_size_usd / price
        
        # Apply exchange-specific precision rules
        precision = self._get_amount_precision(base_currency)
        if precision > 0:
            amount = round(amount, precision)
        
        # Ensure minimum amount
        min_amount = self._get_minimum_amount(base_currency)
        if amount < min_amount:
            self.logger.warning(f"⚠️  Amount {amount} below minimum {min_amount}, adjusting")
            amount = min_amount
        
        return amount
    
    def _get_amount_precision(self, currency: str) -> int:
        """Get precision for amount rounding based on currency."""
        precision_map = {
            'BTC': 6,
            'ETH': 4,
            'USDT': 2,
            'USDC': 2,
            'USD': 2
        }
        return precision_map.get(currency, 8)
    
    def _get_minimum_amount(self, currency: str) -> float:
        """Get minimum trade amount for currency."""
        min_amount_map = {
            'BTC': 0.0001,
            'ETH': 0.001,
            'USDT': 10.0,
            'USDC': 10.0,
            'USD': 10.0
        }
        return min_amount_map.get(currency, 0.01)
    
    def _validate_execution_params(self, buy_exchange: str, sell_exchange: str,
                                 buy_price: float, sell_price: float,
                                 symbol: str, amount: float,
                                 expected_profit: float) -> bool:
        """Validate all execution parameters before proceeding."""
        if buy_price <= 0 or sell_price <= 0:
            self.logger.error(f"❌ Invalid prices: buy=${buy_price:.2f}, sell=${sell_price:.2f}")
            return False
        
        if amount <= 0:
            self.logger.error(f"❌ Invalid amount: {amount}")
            return False
        
        if buy_exchange == sell_exchange:
            self.logger.error(f"❌ Same exchange for buy and sell: {buy_exchange}")
            return False
        
        if expected_profit < 0:
            self.logger.warning(f"⚠️  Negative expected profit: ${expected_profit:.2f}")
        
        # Check spread is positive
        if sell_price <= buy_price:
            self.logger.error(f"❌ Negative or zero spread: sell=${sell_price:.2f} <= buy=${buy_price:.2f}")
            return False
        
        return True
    
    def _execute_order(self, exchange_id: str, symbol: str, side: str,
                      amount: float, price_limit: float,
                      order_type: str = 'limit') -> Dict:
        """
        Execute a single order with retry logic.
        
        Returns:
            Dict containing success, price, amount, fee, error
        """
        for attempt in range(self.settings['max_retries']):
            try:
                self.logger.debug(f"   Attempt {attempt + 1}/{self.settings['max_retries']}: "
                                f"{side.upper()} {amount} {symbol} on {exchange_id}")
                
                # Get exchange wrapper (in real implementation, this would be injected)
                # For now, simulate execution
                if order_type == 'limit':
                    # Simulate limit order execution
                    execution_price = price_limit * (0.999 if side == 'buy' else 1.001)
                    fee_rate = 0.001  # 0.1% taker fee
                else:
                    # Simulate market order execution
                    execution_price = price_limit
                    fee_rate = 0.002  # 0.2% taker fee
                
                fee = amount * execution_price * fee_rate
                
                # Simulate random failure (remove in production)
                import random
                if random.random() < 0.05:  # 5% failure rate for simulation
                    raise Exception("Simulated exchange error")
                
                return {
                    'success': True,
                    'price': execution_price,
                    'amount': amount,
                    'fee': fee,
                    'order_type': order_type,
                    'exchange': exchange_id
                }
                
            except Exception as e:
                self.logger.warning(f"   Order attempt {attempt + 1} failed: {e}")
                
                if attempt < self.settings['max_retries'] - 1:
                    time.sleep(self.settings['retry_delay'] * (2 ** attempt))
                else:
                    return {
                        'success': False,
                        'error': str(e),
                        'exchange': exchange_id
                    }
        
        return {'success': False, 'error': 'Max retries exceeded'}
    
    def _hedge_position(self, original_buy_exchange: str, failed_sell_exchange: str,
                       symbol: str, amount: float, buy_price: float) -> bool:
        """Hedge a position when one leg fails."""
        self.logger.warning(f"⚠️  Hedging position: {amount} {symbol} at ${buy_price:.2f}")
        
        # Find alternative exchange for hedging
        # In production, this would query available exchanges
        alternative_exchanges = ['KRAKEN', 'BINANCE', 'COINBASE']
        alternative_exchanges.remove(original_buy_exchange)
        if failed_sell_exchange in alternative_exchanges:
            alternative_exchanges.remove(failed_sell_exchange)
        
        if not alternative_exchanges:
            self.logger.error("❌ No alternative exchanges available for hedging")
            return False
        
        hedge_exchange = alternative_exchanges[0]
        
        # Execute hedge (sell at market to minimize further loss)
        self.logger.info(f"🛡️  Hedging on {hedge_exchange} at market price")
        hedge_result = self._execute_order(
            exchange_id=hedge_exchange,
            symbol=symbol,
            side='sell',
            amount=amount,
            price_limit=buy_price * 0.95,  # Accept 5% loss to exit
            order_type='market'
        )
        
        if hedge_result['success']:
            hedge_price = hedge_result['price']
            hedge_loss = (buy_price - hedge_price) * amount
            self.logger.warning(f"⚠️  Position hedged with loss: ${hedge_loss:.2f}")
            return True
        else:
            self.logger.error(f"❌ Hedge failed: {hedge_result.get('error')}")
            return False
    
    def get_performance_metrics(self) -> Dict:
        """Get execution performance metrics."""
        if self.total_trades == 0:
            win_rate = 0.0
        else:
            win_rate = (self.successful_trades / self.total_trades) * 100
        
        avg_profit = 0.0
        if self.successful_trades > 0:
            avg_profit = self.total_profit / self.successful_trades
        
        return {
            'total_trades': self.total_trades,
            'successful_trades': self.successful_trades,
            'failed_trades': self.failed_trades,
            'total_profit': self.total_profit,
            'total_loss': self.total_loss,
            'net_pnl': self.total_profit - self.total_loss,
            'win_rate': win_rate,
            'avg_profit_per_trade': avg_profit,
            'success_rate': (self.successful_trades / max(self.total_trades, 1)) * 100
        }
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """Get recent trade history."""
        return self.execution_history[-limit:] if self.execution_history else []
    
    def reset_metrics(self):
        """Reset performance metrics."""
        self.total_trades = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.execution_history = []
        self.logger.info("📊 Execution metrics reset")