import logging
import time
from typing import Dict, Optional
from decimal import Decimal, ROUND_DOWN
from core.profit import calculate_net_profit, estimate_slippage
from dotenv import load_dotenv

load_dotenv()

class OrderExecutor:
    def __init__(self, config: Dict, logger: logging.Logger, exchanges: Dict, persistence_manager=None):
        self.config = config
        self.logger = logger
        self.exchanges = exchanges
        self.persistence_manager = persistence_manager
        self.execution_history = []
        self.max_history_size = 100
        self.settings = {
            'max_slippage_percent': config.get('max_slippage_percent', 0.5),
            'max_retries': config.get('max_retries', 3),
            'retry_delay': config.get('retry_delay', 1.0),
            'timeout_seconds': config.get('timeout_seconds', 30),
            'enable_hedging': config.get('enable_hedging', False),
            'hedge_threshold_usd': config.get('hedge_threshold_usd', 1000)
        }
        self.total_trades = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.total_profit = Decimal('0.0')
        self.total_loss = Decimal('0.0')
        self.logger.info("Order executor initialized")

    def execute_arbitrage(self, buy_exchange: str, sell_exchange: str, buy_price: Decimal, sell_price: Decimal,
                          symbol: str, position_size: Decimal, expected_profit: Decimal,
                          trade_params: Optional[Dict] = None) -> bool:
        start_time = time.time()
        self.logger.info(f"Executing arbitrage trade: {symbol}")
        if trade_params is None:
            trade_params = {}
        capital_mode = trade_params.get('capital_mode', 'BALANCED')
        dynamic_position_size = Decimal(str(trade_params.get('dynamic_position_size', position_size)))
        self.logger.info(f"Capital Mode: {capital_mode} | Dynamic Position Size: ${dynamic_position_size:.2f} | Expected Profit: ${expected_profit:.2f}")
        base_currency = symbol.split('/')[0]
        asset_amount = self._calculate_asset_amount(dynamic_position_size, buy_price, base_currency)
        if asset_amount <= 0:
            self.logger.error(f"Invalid asset amount: {asset_amount}")
            return False
        if not self._validate_execution_params(buy_exchange, sell_exchange, buy_price, sell_price, symbol, asset_amount, expected_profit):
            return False
        max_buy_price = buy_price * (Decimal('1') + Decimal(str(self.settings['max_slippage_percent'])) / Decimal('100'))
        min_sell_price = sell_price * (Decimal('1') - Decimal(str(self.settings['max_slippage_percent'])) / Decimal('100'))
        self.logger.info(f"Buying {asset_amount:.6f} {base_currency} on {buy_exchange}")
        buy_result = self._execute_order(buy_exchange, symbol, 'buy', asset_amount, max_buy_price, 'limit')
        if not buy_result['success']:
            self.logger.error(f"Buy order failed: {buy_result.get('error', 'Unknown error')}")
            self.failed_trades += 1
            return False
        actual_buy_price = buy_result['price']
        actual_buy_amount = buy_result['amount']
        buy_fee = buy_result.get('fee', Decimal('0'))
        self.logger.info(f"Selling {actual_buy_amount:.6f} {base_currency} on {sell_exchange}")
        sell_result = self._execute_order(sell_exchange, symbol, 'sell', actual_buy_amount, min_sell_price, 'limit')
        if not sell_result['success']:
            self.logger.error(f"Sell order failed: {sell_result.get('error', 'Unknown error')}")
            if self.settings['enable_hedging']:
                self._hedge_position(buy_exchange, sell_exchange, symbol, actual_buy_amount, actual_buy_price)
            self.failed_trades += 1
            return False
        actual_sell_price = sell_result['price']
        sell_fee = sell_result.get('fee', Decimal('0'))
        net_profit = calculate_net_profit(
            buy_price=actual_buy_price,
            sell_price=actual_sell_price,
            amount=actual_buy_amount,
            fee_buy=buy_fee / (actual_buy_price * actual_buy_amount),
            fee_sell=sell_fee / (actual_sell_price * actual_buy_amount),
            slippage=Decimal('0'),  # Fetch live if order_book available
            transfer_cost=Decimal('0')
        )
        execution_time = time.time() - start_time
        trade_record = {
            'timestamp': datetime.utcnow(),
            'buy_exchange': buy_exchange,
            'sell_exchange': sell_exchange,
            'symbol': symbol,
            'buy_price': actual_buy_price,
            'sell_price': actual_sell_price,
            'amount': actual_buy_amount,
            'net_profit': net_profit,
            'expected_profit': expected_profit,
            'execution_time': execution_time,
            'capital_mode': capital_mode,
            'position_size_usd': dynamic_position_size,
            'success': True
        }
        self.total_trades += 1
        self.successful_trades += 1
        if net_profit > 0:
            self.total_profit += net_profit
        else:
            self.total_loss += abs(net_profit)
        self.execution_history.append(trade_record)
        if len(self.execution_history) > self.max_history_size:
            self.execution_history.pop(0)

        # Persistence to SQLite
        if self.persistence_manager:
            try:
                db_record = {
                    'symbol': symbol,
                    'type': 'ARB_CROSS',
                    'buy_exchange': buy_exchange,
                    'sell_exchange': sell_exchange,
                    'buy_price': actual_buy_price,
                    'sell_price': actual_sell_price,
                    'amount': actual_buy_amount,
                    'fee_usd': buy_fee + sell_fee,
                    'net_profit_usd': net_profit,
                    'execution_time_ms': execution_time * 1000
                }
                self.persistence_manager.save_trade(db_record)
            except Exception as e:
                self.logger.error(f"Failed to persist trade to SQLite: {e}")

        self.logger.info(f"ARBITRAGE EXECUTION COMPLETE: Net Profit ${net_profit:.4f}")
        return True

    def _calculate_asset_amount(self, position_size_usd: Decimal, price: Decimal, base_currency: str) -> Decimal:
        if price <= 0:
            self.logger.error(f"Invalid price for amount calculation: {price}")
            return Decimal('0')
        amount = position_size_usd / price
        precision = self._get_amount_precision(base_currency)
        if precision > 0:
            amount = amount.quantize(Decimal('1') * 10 ** -precision, rounding=ROUND_DOWN)
        min_amount = self._get_minimum_amount(base_currency)
        if amount < min_amount:
            self.logger.warning(f"Amount {amount} below minimum {min_amount}, adjusting")
            amount = min_amount
        return amount

    def _get_amount_precision(self, currency: str) -> int:
        precision_map = {
            'BTC': 6,
            'ETH': 4,
            'USDT': 2,
            'USDC': 2,
            'USD': 2
        }
        return precision_map.get(currency, 8)

    def _get_minimum_amount(self, currency: str) -> Decimal:
        min_amount_map = {
            'BTC': Decimal('0.0001'),
            'ETH': Decimal('0.001'),
            'USDT': Decimal('10.0'),
            'USDC': Decimal('10.0'),
            'USD': Decimal('10.0')
        }
        return min_amount_map.get(currency, Decimal('0.01'))

    def _validate_execution_params(self, buy_exchange: str, sell_exchange: str, buy_price: Decimal,
                                   sell_price: Decimal, symbol: str, amount: Decimal,
                                   expected_profit: Decimal) -> bool:
        if buy_price <= 0 or sell_price <= 0:
            self.logger.error(f"Invalid prices: buy=${buy_price:.2f}, sell=${sell_price:.2f}")
            return False
        if amount <= 0:
            self.logger.error(f"Invalid amount: {amount}")
            return False
        if buy_exchange == sell_exchange:
            self.logger.error(f"Same exchange for buy and sell: {buy_exchange}")
            return False
        if expected_profit < 0:
            self.logger.warning(f"Negative expected profit: ${expected_profit:.2f}")
        if sell_price <= buy_price:
            self.logger.error(f"Negative or zero spread: sell=${sell_price:.2f} <= buy=${buy_price:.2f}")
            return False
        return True

    def _hedge_position(self, original_buy_exchange: str, failed_sell_exchange: str, symbol: str,
                        amount: Decimal, buy_price: Decimal) -> bool:
        self.logger.warning(f"Hedging position: {amount.quantize(Decimal('0.000000'))} {symbol} at ${buy_price.quantize(Decimal('0.00'))}")
        alternative_exchanges = list(self.exchanges.keys())
        alternative_exchanges.remove(original_buy_exchange)
        if failed_sell_exchange in alternative_exchanges:
            alternative_exchanges.remove(failed_sell_exchange)
        if not alternative_exchanges:
            self.logger.error("No alternative exchanges available for hedging")
            return False
        hedge_exchange = alternative_exchanges[0]
        self.logger.info(f"Hedging on {hedge_exchange} at market price")
        hedge_result = self._execute_order(hedge_exchange, symbol, 'sell', amount, buy_price * Decimal('0.95'), 'market')
        if hedge_result['success']:
            hedge_price = hedge_result['price']
            hedge_loss = (buy_price - hedge_price) * amount
            self.logger.warning(f"Position hedged with loss: ${hedge_loss:.2f}")
            return True
        else:
            self.logger.error(f"Hedge failed: {hedge_result.get('error')}")
            return False

    def _execute_order(self, exchange_id: str, symbol: str, side: str, amount: Decimal,
                       price_limit: Decimal, order_type: str = 'limit') -> Dict:
        exchange = self.exchanges.get(exchange_id)
        if not exchange:
            return {'success': False, 'error': 'Exchange not found'}
        for attempt in range(self.settings['max_retries']):
            try:
                self.logger.debug(f"Attempt {attempt + 1}/{self.settings['max_retries']}: {side.upper()} {amount} {symbol} on {exchange_id}")
                order = exchange.place_order(symbol, side, amount, price_limit if order_type == 'limit' else None)
                execution_price = Decimal(order.get('price', price_limit))
                fee_rate = Decimal('0.001')  # Fetch live from fee manager if integrated
                fee = amount * execution_price * fee_rate
                self.logger.info(f"Fetched order execution from API for {exchange_id}")
                return {'success': True, 'price': execution_price, 'amount': amount, 'fee': fee}
            except Exception as e:
                self.logger.warning(f"Order attempt failed: {e}")
                time.sleep(self.settings['retry_delay'])
        return {'success': False, 'error': 'Max retries exceeded'}