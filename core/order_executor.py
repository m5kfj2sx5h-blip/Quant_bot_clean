import logging
import time
import asyncio
from typing import Dict, Optional
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from core.profit import calculate_net_profit, estimate_slippage
from dotenv import load_dotenv

load_dotenv('config/.env')

class OrderExecutor:
    def __init__(self, config: Dict, logger: logging.Logger, exchanges: Dict, persistence_manager=None, fee_manager=None, risk_manager=None):
        self.config = config
        self.logger = logger
        self.exchanges = exchanges
        self.persistence_manager = persistence_manager
        self.fee_manager = fee_manager
        self.risk_manager = risk_manager
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

    async def execute_arbitrage(self, buy_exchange: str, sell_exchange: str, buy_price: Decimal, sell_price: Decimal,
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
            # Leg failed: Monitor and exit based on 1% risk rule
            await self._monitor_and_emergency_exit(buy_exchange, sell_exchange, symbol, actual_buy_amount, actual_buy_price, dynamic_position_size)
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
            'timestamp': datetime.now(timezone.utc),
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

    async def execute_triangular(self, exchange_id: str, path: list, trade_value: Decimal, start_currency: str) -> bool:
        """
        Executes a 3-leg triangular arbitrage on a single exchange.
        Path: [Pair1, Pair2, Pair3] e.g. ['BTC/USDT', 'ETH/BTC', 'ETH/USDT']
        Sequence: Buy Leg 1 -> Sell Leg 2 -> Sell Leg 3 (Example)
        User logic: "Buy BTC with USDT -> Buy ETH with BTC -> Sell ETH for USDT"
        """
        self.logger.info(f"Executing Triangular Arb on {exchange_id}: {' -> '.join(path)}")
        
        # Validation
        if not path or len(path) != 3:
            self.logger.error("Invalid triangular path length")
            return False

        # Leg 1
        qty = Decimal('0')
        # We assume trade_value is in Quote of Pair 1 (USDT)
        # Leg 1: Buy Base1 (BTC) with Quote1 (USDT)
        pair1 = path[0]
        # Need price to calculate quantity
        # Use execute_order with 'limit' or 'market'. Triangular usually requires speed -> Market?
        # User strategy implies limit? "only the order executor places orders"
        # We'll use _execute_order.
        
        # Determine strict sides based on path currencies
        # Standard: USDT -> BTC -> ETH -> USDT
        # 1. BTC/USDT (Buy BTC)
        # 2. ETH/BTC (Buy ETH using BTC)
        # 3. ETH/USDT (Sell ETH for USDT)
        
        # Execute Leg 1
        self.logger.info(f"Leg 1: Buy {pair1}")
        # Fetch price first for amount calc
        try:
            ticker = self.exchanges[exchange_id].get_ticker_price(pair1)
            price1 = ticker.value
            qty1 = trade_value / price1
            
            res1 = self._execute_order(exchange_id, pair1, 'buy', qty1, price1, 'limit')
            if not res1['success']:
                self.logger.error(f"Leg 1 Failed: {res1.get('error')}")
                return False
            
            actual_qty1 = res1['amount'] # BTC Acquired
            
            # Leg 2: Buy ETH with BTC (ETH/BTC)
            pair2 = path[1]
            self.logger.info(f"Leg 2: Buy {pair2} with {actual_qty1} BTC")
            # We are spending actual_qty1 of Quote currency (BTC) to buy Base (ETH)
            # We need price of ETH/BTC
            ticker2 = self.exchanges[exchange_id].get_ticker_price(pair2)
            price2 = ticker2.value
            qty2 = actual_qty1 / price2 # ETH Amount
            
            res2 = self._execute_order(exchange_id, pair2, 'buy', qty2, price2, 'limit')
            if not res2['success']:
                self.logger.critical(f"Leg 2 Failed! Stuck with BTC: {res2.get('error')}")
                # Emergency exit? Sell BTC back to USDT?
                # For now just return False, but in prod we need recovery.
                return False
                
            actual_qty2 = res2['amount'] # ETH Acquired
            
            # Leg 3: Sell ETH for USDT (ETH/USDT)
            pair3 = path[2]
            self.logger.info(f"Leg 3: Sell {pair3} ({actual_qty2} ETH)")
            ticker3 = self.exchanges[exchange_id].get_ticker_price(pair3)
            price3 = ticker3.value
            
            res3 = self._execute_order(exchange_id, pair3, 'sell', actual_qty2, price3, 'limit')
            if not res3['success']:
                self.logger.critical(f"Leg 3 Failed! Stuck with ETH: {res3.get('error')}")
                return False
                
            final_usdt = res3['amount'] * res3['price']
            profit = final_usdt - trade_value
            self.logger.info(f"Triangular Complete. Result: ${profit:.2f}")
            
            # Persist
            if self.persistence_manager:
                self.persistence_manager.save_trade({
                    'symbol': ' -> '.join(path),
                    'type': 'ARB_TRI',
                    'buy_exchange': exchange_id,
                    'amount': float(trade_value),
                    'net_profit_usd': float(profit)
                })
            
            return True

        except Exception as e:
            self.logger.error(f"Triangular Execution Exception: {e}")
            return False

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

    async def _monitor_and_emergency_exit(self, original_buy_exchange: str, failed_sell_exchange: str, symbol: str,
                                amount: Decimal, buy_price: Decimal, allotted_capital: Decimal) -> bool:
        """
        Monitors a position and exits if it hits the 1% risk limit or finds another exit.
        """
        self.logger.warning(f"🚨 MONITORING LEG-FAILED POSITION: {amount} {symbol} bought on {original_buy_exchange} @ ${buy_price}")
        
        while True:
            # Get current price
            current_price = Decimal('0')
            alternative_exchanges = [failed_sell_exchange, original_buy_exchange] + list(self.exchanges.keys())
            
            for ex in alternative_exchanges:
                try:
                    ticker = self.exchanges[ex].get_ticker_price(symbol)
                    current_price = ticker.value
                    if current_price > 0: break
                except:
                    continue
            
            if current_price == 0:
                self.logger.error("Could not fetch current price for emergency monitoring")
                await asyncio.sleep(5)
                continue

            # Check 1% risk rule via RiskManager
            if self.risk_manager and self.risk_manager.check_emergency_exit(symbol, current_price, buy_price, allotted_capital):
                self.logger.critical(f"1% Risk Limit Hit! Executing Emergency Market Exit for {symbol}")
                # Sell anywhere possible at market
                for ex in alternative_exchanges:
                    try:
                        self.logger.info(f"Attempting emergency market sell on {ex}")
                        res = self._execute_order(ex, symbol, 'sell', amount, current_price * Decimal('0.95'), 'market')
                        if res['success']:
                            self.logger.info(f"✅ EMERGENCY EXIT SUCCESS ON {ex}")
                            return True
                    except:
                        continue
                break # Exit loop if failed all exchanges
            
            # Check if we can exit with profit or break-even
            if current_price >= buy_price * Decimal('1.001'): # 0.1% profit buffer
                 self.logger.info(f"Exiting leg-failed position at break-even/profit: ${current_price}")
                 for ex in alternative_exchanges:
                    try:
                        res = self._execute_order(ex, symbol, 'sell', amount, current_price, 'market')
                        if res['success']: return True
                    except: continue
                 break

            await asyncio.sleep(10) # Monitor every 10s
            
        return False

    def _wait_for_fill(self, exchange_id: str, order_id: str, symbol: str) -> Dict:
        """Strict verification loop: Polling get_order until filled or timeout."""
        start = time.time()
        timeout = self.settings.get('timeout_seconds', 30)
        
        while time.time() - start < timeout:
            try:
                # Call adapter standardized method
                res = self.exchanges[exchange_id].get_order(order_id, symbol)
                status = res.get('status', 'unknown')
                
                if status == 'closed': # FILLED
                     self.logger.info(f"Order {order_id} FILLED: {res['filled']} @ {res['avg_price']}")
                     return res
                if status == 'canceled' or status == 'expired' or status == 'rejected':
                     return {'status': 'canceled', 'error': 'Order canceled/rejected by exchange'}
                
                # If PARTIALLY_FILLED, we keep waiting? 
                # For arbitrage atomic execution, we arguably want FULL fill or nothing?
                # But waiting forever on partial is bad.
                # If partial and near timeout, we might accept.
                # For now, Strict: Wait for Closed.
                
            except Exception as e:
                self.logger.warning(f"Polling error for {order_id}: {e}")
            
            time.sleep(self.settings.get('retry_delay', 1.0))
            
        return {'status': 'timeout'}

    def _execute_order(self, exchange_id: str, symbol: str, side: str, amount: Decimal,
                       price_limit: Decimal, order_type: str = 'limit') -> Dict:
        exchange = self.exchanges.get(exchange_id)
        if not exchange:
            return {'success': False, 'error': 'Exchange not found'}
            
        for attempt in range(self.settings['max_retries']):
            try:
                self.logger.debug(f"Attempt {attempt + 1}: {side.upper()} {amount} {symbol} on {exchange_id}")
                
                # --- PAPER MODE ---
                is_paper = str(self.config.get('paper_mode', 'false')).lower() == 'true'
                if is_paper:
                    self.logger.info(f"📝 PAPER MODE: Simulating {side} {amount} {symbol} @ {price_limit}")
                    time.sleep(0.1)
                    return {
                        'success': True, 
                        'price': price_limit if price_limit else Decimal('1000.0'),
                        'amount': amount, 
                        'fee': Decimal('0'),
                        'order_id': f'paper_{int(time.time()*1000)}'
                    }
                # ------------------

                # Place Order
                # Adapters return different structures. We must extract ID robustly.
                order_res = exchange.place_order(symbol, side, amount, price_limit if order_type == 'limit' else None)
                
                order_id = None
                # Binance/Generic Dict
                if isinstance(order_res, dict):
                    if 'orderId' in order_res:
                        order_id = str(order_res['orderId'])
                    elif 'id' in order_res:
                        order_id = str(order_res['id'])
                    # Kraken
                    elif 'result' in order_res and 'txid' in order_res['result']:
                         order_id = order_res['result']['txid'][0]
                # Coinbase Object
                elif hasattr(order_res, 'order_id'):
                    order_id = order_res.order_id
                
                if not order_id:
                     self.logger.error(f"Failed to extract Order ID from response: {order_res}")
                     return {'success': False, 'error': 'No Order ID returned'}
                
                # Strict Verification Loop (No Guessing!)
                self.logger.info(f"Order Placed (ID: {order_id}). Waiting for fill verification...")
                fill_info = self._wait_for_fill(exchange_id, order_id, symbol)
                
                if fill_info.get('status') == 'closed':
                     return {
                         'success': True,
                         'price': fill_info['avg_price'],
                         'amount': fill_info['filled'],
                         'fee': fill_info['fee'],
                         'order_id': order_id
                     }
                elif fill_info.get('status') == 'timeout':
                     self.logger.warning(f"Order {order_id} timed out. Cancelling...")
                     exchange.cancel_order(order_id, symbol)
                     # Check fill status one last time after cancel?
                     # Simplified: Return fail.
                     return {'success': False, 'error': 'Fill Timeout'}
                else:
                     return {'success': False, 'error': f"Order Failed: {fill_info.get('status')}"}

            except Exception as e:
                self.logger.warning(f"Order attempt failed: {e}")
                time.sleep(self.settings['retry_delay'])
                
        return {'success': False, 'error': 'Max retries exceeded'}