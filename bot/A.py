import logging
import os
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime
from collections import OrderedDict
from dotenv import load_dotenv

load_dotenv('config/.env')

logger = logging.getLogger(__name__)

class ABot:
    def __init__(self, config: dict, exchanges: Dict, staking_manager=None, fee_manager=None, market_registry=None, portfolio=None, persistence_manager=None):
        self.config = config
        self.exchanges = exchanges
        self.staking_manager = staking_manager
        self.fee_manager = fee_manager
        self.market_registry = market_registry
        self.portfolio = portfolio
        self.persistence_manager = persistence_manager
        staking_config = config.get('staking', {})
        self.max_slots = staking_config.get('slots', 6)
        self.seat_warmer_empty_threshold = staking_config.get('seat_warmer_empty_threshold', 3)
        self.seat_warmer_full_threshold = staking_config.get('seat_warmer_full_threshold', 2)
        # 15% of capital / 6 slots = 2.5% per slot.
        self.slot_size_pct = Decimal('0.025')
        self.allowed_coins = []  # Dynamic
        self.default_stake_coin = None  # Dynamic
        self.positions = OrderedDict()
        
        # Restore positions from persistence
        if self.persistence_manager:
            stored_positions = self.persistence_manager.load_active_positions()
            if stored_positions:
                for coin, pos in stored_positions.items():
                    self.positions[coin] = pos
                logger.info(f"🎯 A-Bot restored {len(self.positions)} positions from SQLite")
                
        self.running = False
        self.signals_received = 0
        self.trades_executed = 0
        logger.info(f"🎯 A-Bot initialized. Max slots: {self.max_slots}, Slot size: {float(self.slot_size_pct*100)}% of TPV")

    @property
    def slot_size_usd(self) -> Decimal:
        if self.portfolio and self.portfolio.total_value_usd > 0:
            return self.portfolio.total_value_usd * self.slot_size_pct
        return Decimal(str(self.config.get('capital', {}).get('abot_slot_size_usd', 225)))

    def _fetch_allowed_coins(self):
        self.allowed_coins = []
        for exchange in self.exchanges.values():
            try:
                markets = exchange.get_supported_pairs()
                for symbol in markets:
                    coin = symbol.base
                    if coin not in self.allowed_coins:
                        self.allowed_coins.append(coin.upper())
            except:
                continue
        if not self.allowed_coins:
            self.allowed_coins = ['BTC', 'ETH', 'SOL', 'ADA', 'DOT', 'LINK', 'ATOM'] # Fallback
        logger.info(f"Fetched allowed coins from APIs: {len(self.allowed_coins)} coins")

    def _fetch_default_stake_coin(self):
        # From staking manager's highest APY
        if self.staking_manager:
            self.default_stake_coin = self.staking_manager.get_highest_apy_coin()
        if not self.default_stake_coin:
            self.default_stake_coin = 'ETH'  # Good staking fallback (was SOL)
        logger.info(f"Fetched default stake coin from API: {self.default_stake_coin}")

    def get_empty_slots(self) -> int:
        return self.max_slots - len(self.positions)

    def handle_signal(self, action: str, coin: str, data: dict = None) -> bool:
        self.signals_received += 1
        action = action.upper()
        coin = coin.upper()
        logger.info(f"🎯 A-Bot received signal: {action} {coin}")
        
        # Ensure allowed coins are populated
        if not self.allowed_coins:
            self._fetch_allowed_coins()

        if coin not in self.allowed_coins:
            logger.warning(f"⚠️ {coin} not in allowed coins list, ignoring signal")
            return False
        if action == 'BUY':
            return self._execute_buy(coin)
        elif action == 'SELL':
            return self._execute_sell(coin)
        else:
            logger.warning(f"⚠️ Unknown action: {action}")
            return False

    def _execute_buy(self, coin: str) -> bool:
        if len(self.positions) >= self.max_slots:
            logger.warning(f"⚠️ All {self.max_slots} slots full, cannot buy {coin}")
            return False
        if coin in self.positions:
            logger.warning(f"⚠️ Already holding {coin}, ignoring buy signal")
            return False
        best_exchange_name, best_price = self._find_best_buy_price(coin)
        if not best_exchange_name:
            logger.warning(f"⚠️ Could not find exchange to buy {coin} (Exchange/Pair not found)")
            return False
        
        amount = self.slot_size_usd / best_price
        logger.info(f"🎯 Executing BUY {amount:.6f} {coin} on {best_exchange_name} @ ${best_price}")
        
        try:
            exchange = self.exchanges[best_exchange_name]
            pair = f"{coin}/USDT" # Standardizing on USDT for A-Bot buys
            order = exchange.place_order(pair, 'buy', amount, best_price)
            
            self.positions[coin] = {
                'amount': amount,
                'exchange': best_exchange_name,
                'buy_price': best_price,
                'staked': False,
                'timestamp': datetime.now(),
                'is_seat_warmer': False
            }
            
            # Persist to SQLite
            if self.persistence_manager:
                self.persistence_manager.save_position(coin, self.positions[coin])
                self.persistence_manager.save_trade({
                    'symbol': coin,
                    'type': 'SNIPER_BUY',
                    'buy_exchange': best_exchange_name,
                    'buy_price': best_price,
                    'amount': amount,
                    'net_profit_usd': 0
                })

            self.trades_executed += 1
            
            # Immediately try to stake if possible
            self.stake_idle_funds()
            return True
        except Exception as e:
            logger.error(f"❌ BUY execution failed for {coin} on {best_exchange_name}: {e}")
            return False

    def _execute_sell(self, coin: str) -> bool:
        if coin not in self.positions:
            logger.warning(f"⚠️ Not holding {coin}, ignoring sell signal")
            return False
        position = self.positions[coin]
        ex_name = position['exchange']
        exchange = self.exchanges[ex_name]
        
        if position['staked'] and self.staking_manager:
            logger.info(f"📤 Unstaking {coin} before sell")
            try:
                self.staking_manager.unstake(coin, position['amount'])
            except Exception as e:
                logger.error(f"⚠️ Unstaking {coin} failed, attempting sell anyway: {e}")

        logger.info(f"🎯 Executing SELL {position['amount']:.6f} {coin} on {ex_name}")
        try:
            pair = f"{coin}/USDT"
            exchange.place_order(pair, 'sell', position['amount'])
            
            # Record profit and remove from persistence
            if self.persistence_manager:
                self.persistence_manager.remove_position(coin)
                # Fetch price for profit calculation
                ticker = exchange.get_ticker_price(pair)
                sell_price = ticker.value
                profit = (sell_price - position['buy_price']) * position['amount']
                self.persistence_manager.save_trade({
                    'symbol': coin,
                    'type': 'SNIPER_SELL',
                    'sell_exchange': ex_name,
                    'sell_price': sell_price,
                    'amount': position['amount'],
                    'net_profit_usd': profit
                })
                if self.portfolio:
                    self.portfolio.record_arbitrage_profit(profit)

            del self.positions[coin]
            self.trades_executed += 1
            return True
        except Exception as e:
            logger.error(f"❌ SELL execution failed for {coin} on {ex_name}: {e}")
            return False

    def _find_best_buy_price(self, coin: str) -> tuple:
        best_exchange = None
        best_price = None
        # Try both USDT and USDC pairs
        for quote in ['USDT', 'USDC', 'USD']:
            pair = f"{coin}/{quote}"
            for ex_name, exchange in self.exchanges.items():
                try:
                    # Instant Registry Lookup (VRAM Model)
                    book = self.market_registry.get_order_book(ex_name, pair) if self.market_registry else None
                    if book:
                        price = Decimal(str(book.get('ask', book['asks'][0]['price'])))
                    else:
                        ticker = exchange.get_ticker_price(pair)
                        price = ticker.value
                    
                    if best_price is None or price < best_price:
                        best_price = price
                        best_exchange = ex_name
                except Exception:
                    continue
            if best_exchange: break # Found a pair
            
        return best_exchange, best_price

    def _is_market_data_ready(self, coin: str) -> bool:
        """Check if we have market data for the target coin."""
        if not self.market_registry:
            return False
        
        books = self.market_registry.get_all_books()
        if not books:
            return False
            
        # Check if any exchange has a book for this coin
        for ex, pairs in books.items():
            for p in pairs:
                if p.startswith(f"{coin}/"):
                    return True
        return False

    def check_seat_warmers(self) -> None:
        self._fetch_allowed_coins()  # Refresh dynamic
        self._fetch_default_stake_coin()
        
        # Prevent premature execution if registry doesn't have data for our target
        target_coin = self.default_stake_coin
        if self.market_registry and not self._is_market_data_ready(target_coin):
            logger.debug(f"⏳ Market Registry missing data for {target_coin}, skipping seat warmer check")
            return

        empty_slots = self.get_empty_slots()
        if empty_slots > self.seat_warmer_empty_threshold:
            logger.info(f"Chair {empty_slots} empty slots, adding seat warmer")
            self._add_seat_warmer()
        elif empty_slots < self.seat_warmer_full_threshold:
            self._remove_oldest_seat_warmer()

    def _add_seat_warmer(self) -> bool:
        # Cooldown check to prevent log spam
        import time
        if hasattr(self, 'last_seat_warmer_attempt') and time.time() - self.last_seat_warmer_attempt < 60:
            return False
            
        coin = self.default_stake_coin
        if coin in self.positions:
            for c in self.allowed_coins:
                if c not in self.positions:
                    coin = c
                    break
        
        self.last_seat_warmer_attempt = time.time()
        
        if coin in self.positions:
            # logger.warning("All target coins already held...") # Silenced for cleaner logs
            return False
            
        success = self._execute_buy(coin) # Reuse logic
        if success and coin in self.positions:
            self.positions[coin]['is_seat_warmer'] = True
            if self.persistence_manager:
                self.persistence_manager.save_position(coin, self.positions[coin])
        return success

    def _remove_oldest_seat_warmer(self) -> bool:
        # Find oldest seat warmer
        oldest_coin = None
        oldest_time = None
        
        for coin, position in self.positions.items():
            if position.get('is_seat_warmer'):
                if oldest_time is None or position['timestamp'] < oldest_time:
                    oldest_time = position['timestamp']
                    oldest_coin = coin
        
        if oldest_coin:
            logger.info(f"Chair Removing oldest seat warmer: {oldest_coin}")
            return self._execute_sell(oldest_coin)
            
        logger.debug("No seat warmers to remove")
        return False

    def stake_idle_funds(self) -> None:
        if not self.staking_manager:
            return
        for coin, position in self.positions.items():
            if not position['staked']:
                logger.info(f"Staking idle {coin}")
                success = self.staking_manager.stake(coin, position['amount'])
                if success:
                    position['staked'] = True
                    if self.persistence_manager:
                        self.persistence_manager.save_position(coin, position)

    def liquidate_all(self) -> None:
        logger.info("A-Bot liquidating all positions for mode change")
        for coin in list(self.positions.keys()):
            self._execute_sell(coin)

    def get_status(self) -> Dict:
        return {
            'running': self.running,
            'slots_used': len(self.positions),
            'slots_total': self.max_slots,
            'slots_empty': self.get_empty_slots(),
            'positions': {coin: {'exchange': pos['exchange'], 'staked': pos['staked'], 'is_seat_warmer': pos.get('is_seat_warmer', False)} for coin, pos in self.positions.items()},
            'signals_received': self.signals_received,
            'trades_executed': self.trades_executed,
            'allowed_coins': self.allowed_coins
        }

    def get_locked_assets(self) -> Dict[str, Decimal]:
        """Returns dictionary of assets currently held by A-Bot (warmers + trades)."""
        locked = {}
        for coin, position in self.positions.items():
            locked[coin] = locked.get(coin, Decimal('0')) + position['amount']
        return locked