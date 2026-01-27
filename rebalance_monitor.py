import logging
import json
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class RebalanceMonitor:
    def __init__(self, config_path='config/rebalance_config.json'):
        self.config_path = config_path
        # TARGETS for MANUAL MACRO rebalancing (not for auto-trading)
        self.MACRO_TARGET_ALLOCATIONS = {
            'BTC': 0.50,   # Ideal long-term portfolio split for manual review
            'USDT': 0.25,
            'USDC': 0.25
        }
        self.MACRO_TRIGGER_THRESHOLD = 0.10  # 10% deviation triggers a macro review suggestion
        self.MIN_MACRO_TRANSFER_VALUE = 500.0  # Don't suggest manual transfers under $500
        self.last_macro_analysis = None
        self._load_config()
        logger.info(f"⚖️ MACRO Rebalance Monitor Initialized. Suggests manual transfers >${self.MIN_MACRO_TRANSFER_VALUE:.0f}.")

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
                    self.MACRO_TARGET_ALLOCATIONS = loaded_config.get("macro_target_allocations", self.MACRO_TARGET_ALLOCATIONS)
                    self.MACRO_TRIGGER_THRESHOLD = loaded_config.get("macro_trigger_threshold", self.MACRO_TRIGGER_THRESHOLD)
                    self.MIN_MACRO_TRANSFER_VALUE = loaded_config.get("min_macro_transfer_value", self.MIN_MACRO_TRANSFER_VALUE)
        except Exception as e:
            logger.error(f"Failed to load macro config: {e}. Using defaults.")

    def should_rebalance(self, exchange_wrappers, price_data):
        """
        [LEGACY FUNCTION - Called by old system_orchestrator logic.
         Kept for compatibility but now returns False.
         The new inventory logic is in system_orchestrator._check_inventory_needs]
        """
        # This function is no longer used for triggering auto-rebalance.
        # It's kept to avoid breaking the orchestrator's call.
        return False

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
            total_portfolio_value = 0.0

            for wrapper in exchange_wrappers.values():
                exchange_name = wrapper.name
                for currency, amount in wrapper.balances.items():
                    if amount <= 0:
                        continue

                    if currency in ['USDT', 'USDC', 'USD']:
                        value = float(amount)
                        total_values[currency] = total_values.get(currency, 0.0) + value
                        total_portfolio_value += value
                    elif currency == 'BTC':
                        btc_value = self._get_btc_value_for_exchange(exchange_name, amount, price_data)
                        if btc_value > 0:
                            total_values['BTC'] = total_values.get('BTC', 0.0) + btc_value
                            total_portfolio_value += btc_value

            if total_portfolio_value <= 0:
                return None

            current_allocations = {asset: value / total_portfolio_value for asset, value in total_values.items()}

            # 2. Check for significant deviation from MACRO targets
            needs_macro_review = False
            for asset, target in self.MACRO_TARGET_ALLOCATIONS.items():
                current = current_allocations.get(asset, 0)
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
            for exch_name, wrapper in exchange_wrappers.items():
                price = self._get_btc_value_for_exchange(exch_name, 1.0, price_data)  # Value of 1 BTC
                if price:
                    btc_prices[exch_name] = price

            if len(btc_prices) >= 2:
                highest_exchange = max(btc_prices, key=btc_prices.get)
                lowest_exchange = min(btc_prices, key=btc_prices.get)
                price_diff_pct = (btc_prices[highest_exchange] - btc_prices[lowest_exchange]) / btc_prices[lowest_exchange] * 100

                if price_diff_pct > 0.5:  # If spread is meaningful
                    # Calculate how much BTC we could move (respecting reserves)
                    source_btc = exchange_wrappers[highest_exchange].free_balances.get('BTC', 0)
                    movable_btc = max(0, source_btc - min_btc_reserve)

                    if movable_btc * btc_prices[highest_exchange] > self.MIN_MACRO_TRANSFER_VALUE:
                        action = {
                            'type': 'MOVE_BTC',
                            'from': highest_exchange,
                            'to': lowest_exchange,
                            'suggested_amount_btc': round(movable_btc * 0.5, 6),  # Suggest moving 50% of excess
                            'reason': f'Price arbitrage support. {highest_exchange} price (${btc_prices[highest_exchange]:.2f}) is {price_diff_pct:.2f}% higher than {lowest_exchange}.'
                        }
                        plan['suggested_actions'].append(action)
                        plan['priority'] = 'HIGH'

            # 5. Suggest stabilizing stablecoins across exchanges
            stable_balances = {}
            for exch_name, wrapper in exchange_wrappers.items():
                stable_balance = sum(wrapper.free_balances.get(c, 0) for c in ['USDT', 'USDC', 'USD'])
                stable_balances[exch_name] = stable_balance

            avg_stable = sum(stable_balances.values()) / len(stable_balances) if stable_balances else 0
            for exch_name, balance in stable_balances.items():
                deviation = balance - avg_stable
                if abs(deviation) > self.MIN_MACRO_TRANSFER_VALUE:
                    if deviation > 0:
                        # This exchange has excess stablecoins
                        target_exchange = min(stable_balances, key=stable_balances.get)
                        if target_exchange != exch_name:
                            action = {
                                'type': 'MOVE_STABLE',
                                'from': exch_name,
                                'to': target_exchange,
                                'suggested_amount_usd': round(abs(deviation) * 0.5, 2),
                                'reason': f'Balance stabilization. {exch_name.upper()} has ${balance:.0f} stable vs average ${avg_stable:.0f}.'
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
            logger.error(f"Failed to generate macro plan: {e}", exc_info=True)
            return None

    def _get_btc_value_for_exchange(self, exchange_name, btc_amount, price_data):
        """Get BTC value for a specific exchange using available price data"""
        btc_pairs = ['BTC/USDT', 'BTC/USDC', 'BTC/USD']

        for pair in btc_pairs:
            if pair in price_data and exchange_name in price_data[pair]:
                price_info = price_data[pair][exchange_name]
                if 'bid' in price_info and price_info['bid']:
                    return float(btc_amount) * float(price_info['bid'])

        for pair, exchanges in price_data.items():
            if 'BTC' in pair and exchange_name in exchanges:
                price_info = exchanges[exchange_name]
                if 'bid' in price_info and price_info['bid']:
                    return float(btc_amount) * float(price_info['bid'])

        return 0.0