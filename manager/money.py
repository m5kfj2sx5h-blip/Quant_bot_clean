# Was rebalance_monitor.py and name changed to manager/money.py

import logging
import json
from datetime import datetime
from decimal import Decimal
import os
from manager.conversion import ConversionManager  # For fee-free triangular
from manager.mode import ModeManager  # For GOLD/BTC allotment

logger = logging.getLogger(__name__)

class MoneyManager:

    def __init__(self, config_path='config/rebalance_config.json'):
        self.config_path = config_path
        # TARGETS for MANUAL MACRO rebalancing (not for auto-trading)
        self.MACRO_TARGET_ALLOCATIONS = {
            'BTC': Decimal('0.50'),  # Ideal long-term portfolio split for manual review
            'USDT': Decimal('0.25'),
            'USDC': Decimal('0.25')
        }
        self.MACRO_TRIGGER_THRESHOLD = Decimal('0.10')  # 10% deviation triggers a macro review suggestion
        self.MIN_MACRO_TRANSFER_VALUE = Decimal('500.0')  # Don't suggest manual transfers under $500
        self.last_macro_analysis = None
        self.mode_manager = ModeManager()  # For GOLD/BTC mode
        self.conversion_manager = ConversionManager()  # For fee-free triangular
        self.latency_mode = os.getenv('LATENCY_MODE', 'laptop').lower()
        self.drift_threshold = Decimal('0.15') if self.latency_mode == 'laptop' else Decimal(
            '0.10')  # High: 15%, Low: 10%
        self.capital_mode = "balanced"  # Default, update in check_drift
        self._load_config()
        logger.info(
            f"⚖️ MACRO MONEY MANAGER Initialized. Suggests MANUAL transfers >${self.MIN_MACRO_TRANSFER_VALUE:.0f}. Latency mode: {self.latency_mode.upper()}, Drift threshold: {self.drift_threshold * Decimal('100')}%")

    def _load_config(self):
        default_config = {
            "macro_target_allocations": self.MACRO_TARGET_ALLOCATIONS,
            "macro_trigger_threshold": self.MACRO_TRIGGER_THRESHOLD,
            "min_macro_transfer_value": self.MIN_MACRO_TRANSFER_VALUE
        }
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)
                    self.MACRO_TARGET_ALLOCATIONS = {k: Decimal(str(v)) for k, v in
                                                     loaded_config.get("macro_target_allocations",
                                                                       self.MACRO_TARGET_ALLOCATIONS).items()}
                    self.MACRO_TRIGGER_THRESHOLD = Decimal(
                        str(loaded_config.get("macro_trigger_threshold", self.MACRO_TRIGGER_THRESHOLD)))
                    self.MIN_MACRO_TRANSFER_VALUE = Decimal(
                        str(loaded_config.get("min_macro_transfer_value", self.MIN_MACRO_TRANSFER_VALUE)))
        except Exception as e:
            logger.error(f"❌ Failed to load macro config: {e}. Using defaults.")

    def generate_macro_plan(self, exchange_wrappers, price_data, min_btc_reserve, min_stable_reserve):
        """
        Generates a SMART MANUAL plan for MACRO rebalancing.
        Returns a plan dictionary, or None if no major action is needed.
        """
        try:
            if not price_data:
                return None

            # 1. Calculate total portfolio value and allocation (for information only)
            total_values = {}
            total_portfolio_value = Decimal('0.0')

            for wrapper in exchange_wrappers.values():
                exchange_name = wrapper.name
                for currency, amount in wrapper.balances.items():
                    if amount <= Decimal('0'):
                        continue

                    if currency in ['USDT', 'USDC', 'USD']:
                        value = Decimal(str(amount))
                        total_values[currency] = total_values.get(currency, Decimal('0.0')) + value
                        total_portfolio_value += value
                    elif currency == 'BTC':
                        btc_value = self._get_btc_value_for_exchange(exchange_name, amount, price_data)
                        if btc_value > Decimal('0'):
                            total_values['BTC'] = total_values.get('BTC', Decimal('0.0')) + btc_value
                            total_portfolio_value += btc_value

            if total_portfolio_value <= Decimal('0'):
                return None

            current_allocations = {asset: value / total_portfolio_value for asset, value in total_values.items()}

            # Add capital mode
            total_stable = sum(total_values.get(c, Decimal('0.0')) for c in ['USDT', 'USDC', 'USD'])
            self.capital_mode = "bottlenecked" if total_stable < Decimal('1500') else "balanced"
            logger.info(f"Capital mode: {self.capital_mode.upper()} (stable: ${total_stable:.2f})")

            # Allot capital per GOLD/BTC mode from mode_manager
            current_mode = self.mode_manager.get_current_mode()  # 'BTC' or 'GOLD'
            if current_mode == 'BTC':
                arb_pct = Decimal('0.85')
                staking_pct = Decimal('0.15')
                hedging_pct = Decimal('0.0')
            else:  # GOLD
                arb_pct = Decimal('0.15')
                staking_pct = Decimal('0.0')
                hedging_pct = Decimal('0.85')
            logger.info(
                f"Capital allotment ({current_mode}): Arb {arb_pct * 100}%, Staking {staking_pct * 100}%, Hedging {hedging_pct * 100}%")

            # Apply allotment (simplified—adjust balances target)
            target_btc = total_portfolio_value * (arb_pct + hedging_pct)  # BTC for arb/hedging
            target_stable = total_portfolio_value * staking_pct  # Stable for staking

            # 2. Check for significant deviation from MACRO targets
            needs_macro_review = False
            for asset, target in self.MACRO_TARGET_ALLOCATIONS.items():
                current = current_allocations.get(asset, Decimal('0'))
                if abs(current - target) > self.MACRO_TRIGGER_THRESHOLD:
                    needs_macro_review = True
                    logger.info(f"📊 Macro Review: {asset} is at {current:.1%} vs target {target:.1%}")
                    break

            if not needs_macro_review:
                return None

            # 3. Generate a SMART, PRICE-AWARE manual transfer plan
            plan = {
                'timestamp': datetime.now().isoformat(),
                'total_portfolio_value': total_portfolio_value,
                'current_allocations': current_allocations,
                'target_allocations': self.MACRO_TARGET_ALLOCATIONS,
                'reason': 'Portfolio allocation drift exceeds threshold.',
                'suggested_actions': [],
                'priority': 'MEDIUM'  # LOW, MEDIUM, HIGH
            }

            # 4. Suggest moving BTC from the exchange with the HIGHEST price to the LOWEST (supports arbitrage)
            btc_prices = {}
            for exch_name, wrapper in exchange_wrappers.values():
                price = self._get_btc_value_for_exchange(exch_name, Decimal('1.0'), price_data)  # Value of 1 BTC
                if price:
                    btc_prices[exch_name] = price

            if len(btc_prices) >= 2:
                highest_exchange = max(btc_prices, key=btc_prices.get)
                lowest_exchange = min(btc_prices, key=btc_prices.get)
                price_diff_pct = (btc_prices[highest_exchange] - btc_prices[lowest_exchange]) / btc_prices[
                    lowest_exchange] * Decimal('100')

                if price_diff_pct > Decimal('0.5'):  # If spread is meaningful
                    # Calculate how much BTC we could move (respecting reserves)
                    source_btc = exchange_wrappers[highest_exchange].free_balances.get('BTC', Decimal('0'))
                    movable_btc = max(Decimal('0'), source_btc - min_btc_reserve)

                    if movable_btc * btc_prices[highest_exchange] > self.MIN_MACRO_TRANSFER_VALUE:
                        action = {
                            'type': 'MOVE_BTC',
                            'from': highest_exchange,
                            'to': lowest_exchange,
                            'suggested_amount_btc': (movable_btc * Decimal('0.5')).quantize(Decimal('0.000001')),
                            # Suggest moving 50% of excess
                            'reason': f'Price arbitrage support. {highest_exchange} price (${btc_prices[highest_exchange]:.2f}) is {price_diff_pct:.2f}% higher than {lowest_exchange}.'
                        }
                        plan['suggested_actions'].append(action)
                        plan['priority'] = 'HIGH'

            # 5. Suggest stabilizing stablecoins across exchanges
            stable_balances = {}
            for exch_name, wrapper in exchange_wrappers.values():
                stable_balance = sum(wrapper.free_balances.get(c, Decimal('0')) for c in ['USDT', 'USDC', 'USD'])
                stable_balances[exch_name] = stable_balance

            avg_stable = sum(stable_balances.values()) / Decimal(len(stable_balances)) if stable_balances else Decimal(
                '0')
            for exch_name, balance in stable_balances.items():
                deviation = balance - avg_stable
                if abs(deviation) > self.drift_threshold * avg_stable:
                    if self.latency_mode == 'laptop':  # High latency: Manual alert
                        logger.warning(
                            f"Drift alert: {exch_name} stable ${balance:.2f} vs avg ${avg_stable:.2f}. Manual transfer suggested.")
                        action = {
                            'type': 'MANUAL_MOVE_STABLE',
                            'from': exch_name if deviation > Decimal('0') else target_exchange,
                            'to': target_exchange if deviation > Decimal('0') else exch_name,
                            'suggested_amount_usd': abs(deviation) * Decimal('0.5'),
                            'reason': f'High latency manual: {exch_name} deviation ${deviation:.2f} (threshold {self.drift_threshold * Decimal('100')}%).'
                        }
                        plan['suggested_actions'].append(action)
                    else:  # Low latency: Auto transfer or notify conversion.py
                        logger.info(
                            f"Auto drift correction: {exch_name} deviation ${deviation:.2f} (threshold {self.drift_threshold * Decimal('100')}%).")
                        if abs(deviation) > self.MIN_MACRO_TRANSFER_VALUE:
                            # Notify conversion.py for fee-free triangular
                            self.conversion_manager.detect_triangle(exch_name, target_exchange, deviation,
                                                                    currency='USDT')  # Assume USDT
                            # If no triangular, auto transfer
                            action = {
                                'type': 'AUTO_MOVE_STABLE',
                                'from': exch_name if deviation > Decimal('0') else target_exchange,
                                'to': target_exchange if deviation > Decimal('0') else exch_name,
                                'suggested_amount_usd': abs(deviation) * Decimal('0.5'),
                                'reason': f'Low latency auto: {exch_name} deviation ${deviation:.2f}.'
                            }
                            plan['suggested_actions'].append(action)

            # 6. Finalize and log
            if plan['suggested_actions']:
                logger.info(f"📋 Generated Macro Plan with {len(plan['suggested_actions'])} suggested actions.")
                self.last_macro_analysis = plan
                return plan
            else:
                logger.info("📊 Macro Review: Drift detected, but no cost-effective manual actions suggested.")
                return None

        except Exception as e:
            logger.error(f"❌ Failed to generate macro plan: {e}", exc_info=True)
            return None

    def _get_btc_value_for_exchange(self, exchange_name, btc_amount, price_data):
        """Get BTC value for a specific exchange using available price data"""
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

        return Decimal('0.0')