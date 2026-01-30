import logging
import os
import json
from decimal import Decimal
from typing import Dict, Optional
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv('config/.env')

logger = logging.getLogger(__name__)

class GBot:
    def __init__(self, config: dict, exchanges: Dict, fee_manager=None, market_registry=None, portfolio=None, persistence_manager=None):
        self.config = config
        self.exchanges = exchanges
        self.fee_manager = fee_manager
        self.market_registry = market_registry
        self.portfolio = portfolio
        self.persistence_manager = persistence_manager
        gold_config = config.get('gold', {})
        self.sweep_profit_pct = Decimal(str(gold_config.get('sweep_profit_pct', 15))) / 100
        self.max_sweeps_per_month = gold_config.get('max_sweeps_per_month', 2)
        self.sell_on_mode_flip_pct = Decimal(str(gold_config.get('sell_on_mode_flip_pct', 85))) / 100
        self.keep_forever_pct = Decimal(str(gold_config.get('keep_forever_pct', 15))) / 100
        self.cold_wallet = os.getenv('BASE_WALLET', '')
        self.sweeps_this_month = 0
        self.last_sweep_month = None
        self.total_paxg_accumulated = Decimal('0')
        self.total_paxg_swept = Decimal('0')
        self.running = False
        
        if not self.persistence_manager:
            self.profit_file = Path('logs/gold_profits.json')
            self._load_state()
        else:
            # G-Bot recovery from SQLite
            last_state = self.persistence_manager.load_last_state()
            if last_state:
                self.total_paxg_accumulated = Decimal(str(last_state.get('gold_accumulated_cycle', '0')))
                # Note: sweeps_this_month would need a trades query, but for now we'll keep it simple
                # or add a dedicated gbot_state table if month reset is critical.
                # Actually, we can just use the portfolio state for accumulated gold.
                
        logger.info(f"🏆 G-Bot initialized. Sweep: {float(self.sweep_profit_pct)*100}% of profits, Max: {self.max_sweeps_per_month}/month")

    def _load_state(self):
        try:
            if self.profit_file.exists():
                data = json.loads(self.profit_file.read_text())
                self.sweeps_this_month = data.get('sweeps_this_month', 0)
                self.last_sweep_month = data.get('last_sweep_month')
                self.total_paxg_accumulated = Decimal(str(data.get('total_paxg_accumulated', '0')))
                self.total_paxg_swept = Decimal(str(data.get('total_paxg_swept', '0')))
        except Exception as e:
            logger.warning(f"Could not load G-Bot state: {e}")

    def _save_state(self):
        try:
            self.profit_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'sweeps_this_month': self.sweeps_this_month,
                'last_sweep_month': self.last_sweep_month,
                'total_paxg_accumulated': str(self.total_paxg_accumulated),
                'total_paxg_swept': str(self.total_paxg_swept),
            }
            self.profit_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Could not save G-Bot state: {e}")

    def _check_month_reset(self):
        current_month = datetime.now().strftime('%Y-%m')
        
        if self.persistence_manager:
            self.sweeps_this_month = self.persistence_manager.get_sweeps_count(current_month)
            self.last_sweep_month = current_month
        elif self.last_sweep_month != current_month:
            self.sweeps_this_month = 0
            self.last_sweep_month = current_month
            self._save_state()

    def accumulate_paxg(self, amount_usd: Decimal) -> bool:
        best_exchange, best_price = self._find_best_paxg_price()
        if not best_exchange or not best_price:
            logger.error("Could not find exchange to buy PAXG")
            return False
        paxg_amount = amount_usd / best_price
        logger.info(f"Accumulating {paxg_amount:.6f} PAXG on {best_exchange} @ ${best_price:.2f}")
        try:
            exchange = self.exchanges.get(best_exchange)
            if exchange:
                exchange.place_order('PAXG/USDT', 'buy', paxg_amount, best_price)
                self.total_paxg_accumulated += paxg_amount
                
                if self.portfolio:
                    self.portfolio.gold_accumulated_this_cycle = self.total_paxg_accumulated
                
                if self.persistence_manager:
                    self.persistence_manager.save_trade({
                        'symbol': 'PAXG',
                        'type': 'GOLD_ACCUMULATE',
                        'buy_exchange': best_exchange,
                        'buy_price': best_price,
                        'amount': paxg_amount,
                        'net_profit_usd': 0
                    })
                
                self._save_state()
                return True
        except Exception as e:
            logger.error(f"Error accumulating PAXG: {e}")
            return False

    def handle_mode_flip_to_btc(self) -> Decimal:
        logger.info("G-Bot handling mode flip to BTC - Selling 85%, keeping 15% forever")
        total_sold_usd = Decimal('0')
        for ex_name, exchange in self.exchanges.items():
            try:
                balance = exchange.get_balance('PAXG')
                if balance <= 0:
                    continue
                sell_amount = balance * self.sell_on_mode_flip_pct
                keep_amount = balance * self.keep_forever_pct
                logger.info(f"{ex_name}: Selling {sell_amount:.6f} PAXG, keeping {keep_amount:.6f} forever")
                price = exchange.get_ticker_price('PAXG/USDT').value
                if price:
                    exchange.place_order('PAXG/USDT', 'sell', sell_amount)
                    total_sold_usd += sell_amount * price
            except Exception as e:
                logger.error(f"Error selling PAXG on {ex_name}: {e}")
        logger.info(f"Mode flip complete. Released ${total_sold_usd:.2f} for Q-Bot and A-Bot")
        return total_sold_usd

    def calculate_sweep_amount(self, total_gold_profit_usd: Decimal) -> Dict:
        self._check_month_reset()
        if total_gold_profit_usd <= 0:
            return {'can_sweep': False, 'reason': 'No profits to sweep', 'sweep_amount_usd': Decimal('0'), 'sweeps_remaining': self.max_sweeps_per_month - self.sweeps_this_month}
        if self.sweeps_this_month >= self.max_sweeps_per_month:
            return {'can_sweep': False, 'reason': f'Max sweeps ({self.max_sweeps_per_month}) reached this month', 'sweep_amount_usd': Decimal('0'), 'sweeps_remaining': 0}
        if not self.cold_wallet:
            return {'can_sweep': False, 'reason': 'No cold wallet configured', 'sweep_amount_usd': Decimal('0'), 'sweeps_remaining': self.max_sweeps_per_month - self.sweeps_this_month}
        sweep_amount_usd = total_gold_profit_usd * self.sweep_profit_pct
        return {'can_sweep': True, 'sweep_amount_usd': sweep_amount_usd, 'sweep_pct': float(self.sweep_profit_pct * 100), 'sweeps_remaining': self.max_sweeps_per_month - self.sweeps_this_month, 'cold_wallet': self.cold_wallet[:10] + '...' + self.cold_wallet[-6:] if len(self.cold_wallet) > 20 else self.cold_wallet}

    def execute_manual_sweep(self, total_gold_profit_usd: Decimal) -> bool:
        sweep_info = self.calculate_sweep_amount(total_gold_profit_usd)
        if not sweep_info['can_sweep']:
            logger.warning(f"Cannot sweep: {sweep_info['reason']}")
            return False
        sweep_amount_usd = sweep_info['sweep_amount_usd']
        logger.info(f"MANUAL SWEEP: Sending ${sweep_amount_usd:.2f} worth of PAXG to cold wallet")
        for ex_name, exchange in self.exchanges.items():
            try:
                balance = exchange.get_balance('PAXG')
                price = exchange.get_ticker_price('PAXG/USDT').value
                if balance > 0 and price:
                    paxg_to_sweep = sweep_amount_usd / price
                    if balance >= paxg_to_sweep:
                        logger.info(f"Sweeping {paxg_to_sweep:.6f} PAXG from {ex_name} to {self.cold_wallet}")
                        self.sweeps_this_month += 1
                        self.total_paxg_swept += paxg_to_sweep
                        
                        if self.persistence_manager:
                            self.persistence_manager.save_trade({
                                'symbol': 'PAXG',
                                'type': 'GOLD_SWEEP',
                                'sell_exchange': ex_name,
                                'sell_price': price,
                                'amount': paxg_to_sweep,
                                'net_profit_usd': 0 # Sweep is transfer, not profit/loss
                            })

                        self._save_state()
                        logger.info(f"Sweep complete. Sweeps this month: {self.sweeps_this_month}/{self.max_sweeps_per_month}")
                        return True
            except Exception as e:
                logger.error(f"Error sweeping from {ex_name}: {e}")
        logger.error("Could not complete sweep - insufficient PAXG balance")
        return False

    def _find_best_paxg_price(self) -> tuple:
        best_exchange = None
        best_price = None
        pair = 'PAXG/USDT'
        for ex_name, exchange in self.exchanges.items():
            try:
                # Instant Registry Lookup (VRAM Model)
                book = self.market_registry.get_order_book(ex_name, pair) if self.market_registry else None
                if book:
                    price = Decimal(str(book.get('ask', book['asks'][0]['price'])))
                else:
                    price = exchange.get_ticker_price(pair).value
                
                if best_price is None or price < best_price:
                    best_price = price
                    best_exchange = ex_name
            except Exception as e:
                logger.debug(f"Error fetching {pair} price from {ex_name}: {e}")
        return best_exchange, best_price

    def get_status(self) -> Dict:
        self._check_month_reset()
        return {
            'running': self.running,
            'total_paxg_accumulated': float(self.total_paxg_accumulated),
            'total_paxg_swept': float(self.total_paxg_swept),
            'sweeps_this_month': self.sweeps_this_month,
            'max_sweeps_per_month': self.max_sweeps_per_month,
            'sweeps_remaining': self.max_sweeps_per_month - self.sweeps_this_month,
            'sell_on_flip_pct': float(self.sell_on_mode_flip_pct * 100),
            'keep_forever_pct': float(self.keep_forever_pct * 100),
            'cold_wallet_configured': bool(self.cold_wallet)
        }

    def get_locked_assets(self) -> Dict[str, Decimal]:
        """Returns dictionary of assets locked by G-Bot (PAXG)."""
        if self.total_paxg_accumulated > 0:
            return {'PAXG': self.total_paxg_accumulated}
        return {}