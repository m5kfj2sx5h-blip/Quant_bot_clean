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
        self.drift_threshold = Decimal('0.35')
        self.conversion_manager = ConversionManager(exchanges=exchanges)
        self.transfer_manager = TransferManager(exchanges, 'USDT', True, market_registry)
        self.mode_manager = mode_manager or ModeManager(None, None)
        self.market_registry = market_registry
        self.portfolio = portfolio
        self.capital_mode = "balanced"
        self._cache = {}
        self.cache_ttl = 300  # 5 min
        self.retry_count = 3
        self._load_config()
        logger.info(f"⚖️ MONEY MANAGER Initialized")

    async def update_balances(self):
        """Fetch latest balances and update portfolio state."""
        balances = self._fetch_balances()
        price_data = {} # Need prices for BTC calc... 
        # For initial log, we might accept 0 for BTC if prices aren't ready, 
        # OR we try to fetch from registry?
        if self.market_registry:
            # Quick price reconstruction
            books = self.market_registry.get_all_books() or {}
            # Flatten to expected price_data format logic if possible, 
            # but simpler: just assume USDT/USD are 1:1 for TPV estimate
            pass
        
        # Update Portfolio
        if self.portfolio:
            self.portfolio.exchange_balances = {}
            total_portfolio_value = Decimal('0')
            
            from domain.entities import Balance
            for ex_name, balance in balances.items():
                self.portfolio.exchange_balances[ex_name] = {}
                for currency, amount in balance.items():
                    self.portfolio.exchange_balances[ex_name][currency] = Balance(
                        currency=currency, total=amount, free=amount, used=Decimal('0')
                    )
                    # Simplified TPV estimation for startup check
                    if currency in ['USDT', 'USDC', 'USD', 'PAXG']: # PAXG ~ Spot Gold
                        total_portfolio_value += amount
                        # Note: BTC value skipped here if no price data yet, acceptable for init log
            
            self.portfolio.total_value_usd = total_portfolio_value
        
        return balances

    def _load_config(self):
        try:
            import json
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                self.critical_drift_threshold = Decimal(str(config.get('DRIFT_THRESHOLD_CRITICAL', '0.95')))
                self.small_account_mode = config.get('SMALL_ACCOUNT_MODE', True) # Default to True for safety
                logger.info(f"Loaded critical drift threshold: {self.critical_drift_threshold}, Small Account Mode: {self.small_account_mode}")
        except Exception as e:
            logger.warning(f"Failed to load settings: {e}. using default 0.95/True")
            self.critical_drift_threshold = Decimal('0.95')
            self.small_account_mode = True

    def generate_macro_plan(self, price_data, min_btc_reserve, min_stable_reserve):
        # Config reload (mock dynamic reload)
        self._load_config()
        
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
            # 1. Estimate Transfer Cost (Dynamic - NO GUESSING)
            transfer_cost_est = None
            try:
                # Find cheapest withdrawal fee across all exchanges for the drifting assets
                costs = []
                drift_assets = [d[0] for d in drift_data]
                for asset in drift_assets:
                    # Query TransferManager for the absolute best fee available (Live or Registry)
                    fee = self.transfer_manager.get_lowest_fee_estimate(asset)
                    if fee is not None:
                        costs.append(fee)
                
                if costs:
                    transfer_cost_est = min(costs) # Best case scenario
                    logger.info(f"Dynamic Transfer Cost Estimate: ${transfer_cost_est:.2f} (Cheapest found)")
                else:
                    logger.warning("Could not fetch ANY dynamic fees for drift assets. Aborting Transfer Strategy evaluation to prevent guessing.")
                    transfer_cost_est = None

            except Exception as e:
                logger.error(f"Error estimating transfer cost: {e}")
                transfer_cost_est = None
            
            # If we don't know the cost, we cannot proceed with Transfer Strategy
            if transfer_cost_est is None:
                 logger.warning("Skipping Transfer Strategy due to missing fee data. Falling back to Internal Conversion check.")
                 # Fallback logic: Try conversion immediately
                 books = {}
                 if self.market_registry:
                     books = self.market_registry.get_all_books() or {}
                 self.conversion_manager.control_drift(drift_data, books=books)
                 return {}

            # 2. Estimate Conversion Loss (Spread + Fee ~ 0.2%)
            # We take the max drift amount to estimate the impact
            max_drift_amount = max([d[1] for d in drift_data]) * total_portfolio_value
            conversion_loss_est = max_drift_amount * Decimal('0.002')
            
            logger.info(f"Smart Correction Analysis: Transfer Cost (~${transfer_cost_est:.2f}) vs Internal Conversion Loss (~${conversion_loss_est:.2f})")
            
            use_transfer = False
            conversion_tried = False
            
            # Decision Matrix
            if conversion_loss_est < transfer_cost_est:
                if any(d[1] >= self.critical_drift_threshold for d in drift_data):
                    logger.warning(f"Drift is critical (>{self.critical_drift_threshold*100}%) - Forcing Transfer despite higher cost")
                    use_transfer = True
                else:
                    logger.info(f"Internal Conversion is cheaper (Save ${transfer_cost_est - conversion_loss_est:.2f}) - Attempting local fix")
                    
                    books = {}
                    if self.market_registry:
                        books = self.market_registry.get_all_books() or {}
                        
                    conversion_tried = True
                    if self.conversion_manager.control_drift(drift_data, books=books):
                        return {}
                    logger.warning("Internal conversion failed/skipped, falling back to check transfer")
                    use_transfer = True
            else:
                logger.info(f"Transfer is cheaper (Save ${conversion_loss_est - transfer_cost_est:.2f}) - Attempting Transfer")
                use_transfer = True
            
            # --- PHASE 9: POSITIONAL ARB (Smart Rebalancing) ---
            if self.small_account_mode and use_transfer:
                # Calculate Potential Profit from the Drift (Conceptually, the arbitrage profit we made to CAUSE this drift)
                # Or simply: Is the 'Correction Benefit' worth the 'Gas Fee'?
                # Actually, Positional Arb means we tolerate drift until it's huge.
                # So we check: Is the amount to be transferred large enough that the fee is < 1%?
                # Or better: Is (DriftAmount * ArbitrageEdge) > 3 * TransferCost?
                # Simplified Expert Logic: Only transfer if Drift Value > $500 (Hard Min) AND Cost < 1%
                
                # Check 1: Is drift critical?
                is_critical = any(d[1] >= self.critical_drift_threshold for d in drift_data)
                
                if not is_critical:
                    # Check 2: Efficiency Ratio
                    # If we transfer $100 and pay $10 fee, that's 10% loss. Bad.
                    # We want fee < 1% at least. So TransferAmount > 100 * Fee.
                    # transfer_cost_est is the fee.
                    min_efficient_transfer = transfer_cost_est * 100
                    
                    # Estimate value to be moved
                    # drift_data has (asset, pct_deviation).
                    # approx_move_val = max_deviation * total_portfolio
                    max_dev = max([d[1] for d in drift_data])
                    approx_move_val = max_dev * total_portfolio_value
                    
                    if approx_move_val < min_efficient_transfer:
                        logger.info(f"🛑 Positional Arb: Drift (${approx_move_val:.2f}) too small for efficient transfer (Need >${min_efficient_transfer:.2f}). Accumulating.")
                        use_transfer = False
                        # Also suppress conversion if it's just rebalancing
                        # If we block transfer, do we fallback to conversion? 
                        # NO, positional arb means we HOLD the drift.
                        return {}
                    else:
                        logger.info(f"✅ Positional Arb: Drift (${approx_move_val:.2f}) large enough for efficient transfer (Fee < 1%). Proceeding.")
            # ----------------------------------------------------

            if use_transfer:
                try:
                    logger.info("Running Transfer Manager to balance accounts...")
                    # balance_accounts returns True if action was taken, False if skipped
                    if not self.transfer_manager.balance_accounts():
                         logger.warning("Transfer Manager skipped (e.g. min amount or no path).")
                         if not conversion_tried:
                             logger.info("FALLING BACK TO INTERNAL CONVERSION.")
                             self.conversion_manager.control_drift(drift_data)
                         else:
                             logger.warning("Drift Unresolvable: Both Conversion and Transfer strategies failed/skipped for this cycle.")
                             
                except Exception as e:
                    logger.error(f"Transfer Manager failed: {e}.")
                    if not conversion_tried:
                        logger.info("FALLING BACK TO INTERNAL CONVERSION.")
                        self.conversion_manager.control_drift(drift_data)
                    else:
                        logger.warning("Drift Unresolvable: Both Conversion and Transfer strategies failed/skipped for this cycle.")
        
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