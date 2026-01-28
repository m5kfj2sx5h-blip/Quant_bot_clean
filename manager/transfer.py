from utils.logger import get_logger
from decimal import Decimal
import os
from core.health_monitor import HealthMonitor
from manager.registry import MarketRegistry
from dotenv import load_dotenv

load_dotenv()

logger = get_logger(__name__)

class TransferManager:
    def __init__(self, exchanges, stable, auto, registry: MarketRegistry = None):
        self.exchanges = exchanges
        self.stable = stable
        self.auto = auto
        self.registry = registry
        self.latency_mode = os.getenv('LATENCY_MODE', 'laptop').lower()
        self.health = HealthMonitor(None, None, {})
        self.supported_nets = []  # Dynamic
        if not self.registry:
            self._fetch_supported_nets()

    def _fetch_supported_nets(self):
        # Legacy fallback if registry not provided
        self.supported_nets = []
        for name, exchange in self.exchanges.items():
            try:
                fees = exchange.get_asset_metadata()
                nets = list(fees['USDT']['networks'].keys())
                for net in nets:
                    if net not in self.supported_nets:
                        self.supported_nets.append(net)
            except:
                continue
        logger.info(f"Fetched supported nets from APIs (Legacy): {self.supported_nets}")

    def balance_accounts(self):
        balances = {name: exchange.get_balance(self.stable) for name, exchange in self.exchanges.items()}
        avg = sum(balances.values()) / Decimal(len(balances))
        for name, bal in balances.items():
            if bal < avg * Decimal('0.9'):
                from_name = max(balances, key=balances.get)
                amount = (avg - bal) / Decimal('2')
                best_fee, best_net, best_speed = self.get_best_net(from_name, name, amount)
                if best_fee is None:
                    logger.warning(f"No suitable net for transfer {amount.quantize(Decimal('0.00'))} {self.stable} from {from_name} to {name}")
                    continue
                logger.info(f"Best net: {best_net} (fee {best_fee.quantize(Decimal('0.00'))}, speed {best_speed}s)")
                if self.auto:
                    # Instant Address lookup from Registry
                    address = self.registry.get_address(name, self.stable) if self.registry else None
                    if not address:
                        address = self.exchanges[name].fetch_deposit_address(self.stable, best_net)['address']
                    
                    self.exchanges[from_name].withdraw(self.stable, amount, address, best_net)
                    logger.info(f"AUTO X TRANSFER {amount.quantize(Decimal('0.00'))} {self.stable} from {from_name} to {name} via {best_net}")
                else:
                    logger.warning(f"MANUAL X TRANSFER NEEDED!! : {amount.quantize(Decimal('0.00'))} {self.stable} from {from_name} to {name} via {best_net}, fee {best_fee.quantize(Decimal('0.00'))}")

    def get_best_net(self, from_name, to_name, amount: Decimal):
        # Use Registry for instant fee/status lookup
        candidates = []
        networks = ['TRX', 'SOL', 'BASE', 'BSC', 'MATIC', 'KRAKEN']
        
        for net in networks:
            if self.registry:
                fee = self.registry.get_fee(from_name, self.stable, net)
                is_online = self.registry.is_network_online(from_name, self.stable, net)
                if fee is not None and is_online:
                    speed = self.health.latency_metrics[from_name][-1] if self.health.latency_metrics[from_name] else Decimal('10')
                    if net == 'ERC20' and amount < Decimal('10000'):
                        continue
                    score = fee + (speed * Decimal('0.1'))
                    candidates.append((fee, net, speed, score))
            else:
                # Legacy fallback
                pass

        if not candidates:
            return None, None, None
        best = min(candidates, key=lambda x: x[3])
        return best[0], best[1], best[2]

    def get_transfer_fee(self, from_name, to_name):
        fees = self.exchanges[from_name].fetch_deposit_withdraw_fees([self.stable])
        nets = fees[self.stable]['networks']
        best_net = min(nets, key=lambda n: nets[n]['withdraw']['fee'])
        return nets[best_net]['withdraw']['fee'], best_net

    def transfer(self, asset, from_name, to_name, amount: Decimal):
        if self.auto:
            net = self.get_best_net(from_name, to_name, amount)[1]
            address = self.exchanges[to_name].fetch_deposit_address(asset)['address']
            self.exchanges[from_name].withdraw(asset, amount, address, {'network': net})