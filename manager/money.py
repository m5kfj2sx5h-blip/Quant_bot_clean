import logging
from decimal import Decimal
from typing import Dict
from datetime import datetime
from manager.conversion import ConversionManager
from manager.mode import ModeManager
from manager.transfer import TransferManager
from utils.logger import get_logger
from dotenv import load_dotenv
import time

load_dotenv('config/.env')

logger = get_logger(__name__)

class MoneyManager:
    def __init__(self, config_path='config/settings.json', exchanges: Dict = None, staking_manager=None, signals_manager=None, mode_manager=None, market_registry=None, portfolio=None):
        self.config_path = config_path
        self.exchanges = exchanges
        self.staking_manager = staking_manager
        self.signals_manager = signals_manager
        self.drift_threshold = Decimal('0.15')
        self.conversion_manager = ConversionManager(exchanges=exchanges)
        self.transfer_manager = TransferManager(exchanges, 'USDT', True, market_registry)
        self.mode_manager = mode_manager or ModeManager(None, None)
        self.portfolio = portfolio
        self.capital_mode = "balanced"
        self._cache = {}
        self.cache_ttl = 300  # 5 min
        self.retry_count = 3
        # self._load_config()
        logger.info(f"⚖️ MONEY MANAGER Initialized")

    def _load_config(self):
        pass  # No ops values

    def generate_macro_plan(self, price_data, min_btc_reserve, min_stable_reserve):
        from domain.entities import Balance
        balances = self._fetch_balances()
        total_values = {}
        total_portfolio_value = Decimal('0.0')
        
        # Clear and rebuild exchange balances in portfolio
        if self.portfolio:
            self.portfolio.exchange_balances = {}

        for ex_name, balance in balances.items():
            if self.portfolio and ex_name not in self.portfolio.exchange_balances:
                self.portfolio.exchange_balances[ex_name] = {}
                
            for currency, amount in balance.items():
                # Add to portfolio aggregate
                if self.portfolio:
                    self.portfolio.exchange_balances[ex_name][currency] = Balance(
                        currency=currency,
                        free=amount,
                        used=Decimal('0'),
                        total=amount
                    )

                if amount <= Decimal('0'):
                    continue
                if currency in ['USDT', 'USDC', 'USD']:
                    value = amount
                    total_values[currency] = total_values.get(currency, Decimal('0.0')) + value
                    total_portfolio_value += value
                elif currency == 'BTC':
                    btc_value = self._get_btc_value_for_exchange(ex_name, amount, price_data)
                    if btc_value > Decimal('0'):
                        total_values['BTC'] = total_values.get('BTC', Decimal('0.0')) + btc_value
                        total_portfolio_value += btc_value
        
        if total_portfolio_value <= Decimal('0'):
            return None
            
        if self.portfolio:
            self.portfolio.total_value_usd = total_portfolio_value
            
        current_allocations = {asset: value / total_portfolio_value for asset, value in total_values.items()}
        total_stable = sum(total_values.get(c, Decimal('0.0')) for c in ['USDT', 'USDC', 'USD'])

        # Determine mode-specific allotments first
        current_mode = self.mode_manager.get_current_mode()
        if current_mode == 'btc_mode' or current_mode == 'BTC':
            arb_pct, staking_pct, hedging_pct = Decimal('0.85'), Decimal('0.15'), Decimal('0.0')
        else:
            arb_pct, staking_pct, hedging_pct = Decimal('0.15'), Decimal('0.0'), Decimal('0.85')
            
        # Dynamic Capital mode bottleneck detection (15% of Q-Bot's allocated capital)
        bottleneck_threshold = total_portfolio_value * arb_pct * Decimal('0.15')
        self.capital_mode = "bottlenecked" if total_stable < bottleneck_threshold else "balanced"
        
        logger.info(f"Capital mode: {self.capital_mode.upper()} (stable: ${total_stable:.2f}, threshold: ${bottleneck_threshold:.2f})")
        logger.info(f"Capital allotment ({current_mode}): Arb {arb_pct * 100}%, Staking {staking_pct * 100}%, Hedging {hedging_pct * 100}%")

        drift_data = []
        for asset, current in current_allocations.items():
            # Simplified drift check: target is proportional to mode
            target = arb_pct if asset == 'BTC' else (staking_pct if asset in ['USDT', 'USDC'] else Decimal('0'))
            deviation = abs(current - target)
            if deviation >= self.drift_threshold:
                drift_data.append((asset, deviation))
        
        if drift_data:
            logger.info(f"Drift detected for {len(drift_data)} assets. Analyzing Smart Correction Cost...")
            
            # Smart Drift Logic: Compare Transfer Cost vs Conversion Loss
            # 1. Estimate Transfer Cost (Default Estimates based on research)
            # Solana/AVAX: ~$0.10, TRON: ~$1.00, ERC20: ~$5.00
            transfer_cost_est = Decimal('5.00') # Conservative default
            # TODO: Future optimization - query TransferManager for exact network fee
            
            # 2. Estimate Conversion Loss (Spread + Fee ~ 0.2%)
            # We take the max drift amount to estimate the impact
            max_drift_amount = max([d[1] for d in drift_data]) * total_portfolio_value
            conversion_loss_est = max_drift_amount * Decimal('0.002')
            
            logger.info(f"Smart Correction Analysis: Transfer Cost (~${transfer_cost_est}) vs Internal Conversion Loss (~${conversion_loss_est:.2f})")
            
            use_transfer = False
            # Decision Matrix
            if conversion_loss_est < transfer_cost_est:
                if any(d[1] >= Decimal('0.35') for d in drift_data):
                    logger.warning("Drift is critical (>35%) - Forcing Transfer despite higher cost")
                    use_transfer = True
                else:
                    logger.info(f"Internal Conversion is cheaper (Save ${transfer_cost_est - conversion_loss_est:.2f}) - Attempting local fix")
                    if self.conversion_manager.control_drift(drift_data):
                        return {}
                    logger.warning("Internal conversion failed/skipped, falling back to check transfer")
                    use_transfer = True
            else:
                logger.info(f"Transfer is cheaper (Save ${conversion_loss_est - transfer_cost_est:.2f}) - Attempting Transfer")
                use_transfer = True

            if use_transfer:
                try:
                    logger.info("Running Transfer Manager to balance accounts...")
                    self.transfer_manager.balance_accounts()
                except Exception as e:
                    logger.error(f"Transfer Manager failed: {e}. FALLING BACK TO INTERNAL CONVERSION.")
                    # Resilience: Fallback to conversion if transfer fails
                    self.conversion_manager.control_drift(drift_data)
        
        return {}

    def _fetch_balances(self) -> Dict:
        cache_key = 'balances'
        if cache_key in self._cache and time.time() - self._cache[cache_key]['timestamp'] < self.cache_ttl:
            return self._cache[cache_key]['data']
        balances = {}
        for ex_name, exchange in self.exchanges.items():
            for attempt in range(self.retry_count):
                try:
                    balances[ex_name] = exchange.get_balance()
                    logger.info(f"Fetched balances from API for {ex_name}")
                    break
                except Exception as e:
                    logger.warning(f"Balance fetch attempt {attempt+1} failed for {ex_name}: {e}")
                    if attempt == self.retry_count - 1:
                        raise Exception(f"Failed to fetch balances for {ex_name}")
                    time.sleep(1)
        self._cache[cache_key] = {'data': balances, 'timestamp': time.time()}
        return balances

    def _get_btc_value_for_exchange(self, exchange_name, btc_amount, price_data):
        try:
            btc_pairs = ['BTC/USDT', 'BTC/USDC', 'BTC/USD']
            for pair in btc_pairs:
                if pair in price_data and exchange_name in price_data[pair]:
                    price_info = price_data[pair][exchange_name]
                    if 'bid' in price_info and price_info['bid']:
                        return Decimal(str(btc_amount)) * Decimal(str(price_info['bid']))
            for pair, exchanges in price_data.items():
                if 'BTC' in pair and exchange_name in exchanges:
                    price_info = exchanges[exchange_name]
                    if 'bid' in price_info and price_info['bid']:
                        return Decimal(str(btc_amount)) * Decimal(str(price_info['bid']))
        except Exception as e:
            logger.error(f"Error fetching BTC value for {exchange_name}: {e}")
        return Decimal('0.0')