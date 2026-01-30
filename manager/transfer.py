from utils.logger import get_logger
from decimal import Decimal
import os
from core.health_monitor import HealthMonitor
from manager.registry import MarketRegistry
from dotenv import load_dotenv

load_dotenv('config/.env')

logger = get_logger(__name__)

class TransferManager:
    def __init__(self, exchanges, stable, auto, registry: MarketRegistry = None, config: dict = None):
        self.exchanges = exchanges
        self.stable = stable
        self.auto = auto
        self.registry = registry
        self.config = config or {}
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

    def balance_accounts(self) -> bool:
        """Balances accounts. Returns True if a transfer was executed, False otherwise (e.g. skipped)."""
        balances = {name: exchange.get_balance(self.stable) for name, exchange in self.exchanges.items()}
        if not balances:
            return False
            
        avg = sum(balances.values()) / Decimal(len(balances))
        transfer_executed = False
        
        for name, bal in balances.items():
            if bal < avg * Decimal('0.9'):
                from_name = max(balances, key=balances.get)
                amount = (avg - bal) / Decimal('2')
                
                # Safety Check: Minimum Transfer Size
                min_transfer = Decimal(str(self.config.get('min_transfer_usd', 500)))
                if amount < min_transfer:
                    logger.info(f"Skipping transfer: Amount {amount:.2f} {self.stable} below minimum ${min_transfer} threshold")
                    continue
                    
                best_fee, best_net, best_speed = self.get_best_net(from_name, name, amount)
                if best_fee is None:
                    # Try API fetch if registry failed
                    logger.warning("Registry miss. Attempting live fetch for transfer path...")
                    try:
                        fees = self.exchanges[from_name].fetch_deposit_withdraw_fees([self.stable])
                        if self.stable in fees and 'networks' in fees[self.stable]:
                             nets = fees[self.stable]['networks']
                             # Find cheapest valid network
                             valid_nets = [n for n in nets if nets[n]['withdraw']['enabled'] and nets[n]['deposit']['enabled']]
                             if valid_nets:
                                 best_net = min(valid_nets, key=lambda n: Decimal(str(nets[n]['withdraw']['fee'])))
                                 best_fee = Decimal(str(nets[best_net]['withdraw']['fee']))
                                 best_speed = Decimal('300') # Assume slow
                    except Exception as e:
                        logger.error(f"Live fee fetch failed: {e}")
                
                if best_fee is None:
                    logger.warning(f"No suitable net for transfer {amount.quantize(Decimal('0.00'))} {self.stable} from {from_name} to {name}")
                    continue

                logger.info(f"Best net: {best_net} (fee {best_fee.quantize(Decimal('0.00'))}, speed {best_speed}s)")
                
                if self.auto:
                    # Priority 1: Check Config File (Static Addresses)
                    address = None
                    if self.config.get('transfer_wallets'):
                        wallets = self.config['transfer_wallets'].get(name, {})
                        net_key_map = {'SOL': 'SOL', 'AVAX C-Chain': 'AVAX', 'AVAX': 'AVAX', 'TRC20': 'TRX', 'TRX': 'TRX', 'Sui': 'SUI', 'SUI': 'SUI', 'Algorand': 'ALGO', 'ALGO': 'ALGO'}
                        if best_net in wallets:
                            address = wallets[best_net]
                        else:
                            mapped_key = net_key_map.get(best_net)
                            if mapped_key and mapped_key in wallets:
                                address = wallets[mapped_key]
                        if address:
                            logger.info(f"Using statically configured address for {name} ({best_net}): {address}") 

                    # Priority 2: Registry
                    if not address and self.registry:
                        address = self.registry.get_address(name, self.stable)
                    
                    # Priority 3: API Fetch
                    if not address:
                        try:
                            address = self.exchanges[name].fetch_deposit_address(self.stable, best_net)['address']
                        except Exception as e:
                             logger.error(f"Could not fetch address: {e}")
                             continue

                    try:
                        self.exchanges[from_name].withdraw(self.stable, amount, address, best_net)
                        logger.info(f"AUTO X TRANSFER {amount.quantize(Decimal('0.00'))} {self.stable} from {from_name} to {name} via {best_net}")
                        transfer_executed = True
                    except Exception as e:
                        logger.error(f"Withdrawal failed: {e}")
                        continue
                else:
                    logger.warning(f"MANUAL X TRANSFER NEEDED!! : {amount.quantize(Decimal('0.00'))} {self.stable} from {from_name} to {name} via {best_net}, fee {best_fee.quantize(Decimal('0.00'))}")
                    transfer_executed = True # Considered 'handled' even if manual
        
        return transfer_executed

    def get_best_net(self, from_name, to_name, amount: Decimal):
        # Use Registry for instant fee/status lookup
        candidates = []
        # Dynamic network list from Registry or fallback
        networks = self.registry.get_supported_networks() if self.registry else self.supported_nets
        if not networks:
            networks = ['TRX', 'SOL', 'BASE', 'BSC', 'MATIC', 'KRAKEN', 'ERC20']
        
        for net in networks:
            fee = None
            speed = Decimal('300')
            if self.registry:
                fee = self.registry.get_fee(from_name, self.stable, net)
                if not self.registry.is_network_online(from_name, self.stable, net):
                     continue
                speed = self.health.latency_metrics[from_name][-1] if self.health.latency_metrics.get(from_name) else Decimal('10')
            
            if fee is not None:
                if net == 'ERC20' and amount < Decimal('10000'):
                    continue # Too expensive usually
                score = fee + (speed * Decimal('0.1'))
                candidates.append((fee, net, speed, score))

        if not candidates:
            return None, None, None
        best = min(candidates, key=lambda x: x[3])
        return best[0], best[1], best[2]

    def get_lowest_fee_estimate(self, asset: str) -> Decimal:
        """Helper for MoneyManager to get cheapest transfer fee across all exchanges."""
        lowest_fee = Decimal('100.0') # High default startup
        found = False
        
        if self.registry:
            networks = self.registry.get_supported_networks()
            for ex in self.exchanges:
                for net in networks:
                    fee = self.registry.get_fee(ex, asset, net)
                    if fee is not None:
                        # Convert to USD if needed (simplified: assume fee is in asset or USD)
                        # In registry, fees are normally standardized to USD or asset amount.
                        # For USDT/USDC it is flat.
                        if fee < lowest_fee:
                            lowest_fee = fee
                            found = True
        
        if not found:
             # Try Live Fetch (One request per exchange)
             for ex_name, exchange in self.exchanges.items():
                 try:
                     fees = exchange.fetch_deposit_withdraw_fees([asset])
                     if asset in fees:
                         nets = fees[asset]['networks']
                         for n in nets:
                             f = Decimal(str(nets[n]['withdraw']['fee']))
                             if f < lowest_fee:
                                 lowest_fee = f
                                 found = True
                 except:
                     pass
                     
        return lowest_fee if found else None

    def transfer(self, asset, from_name, to_name, amount: Decimal):
        if self.auto:
            net = self.get_best_net(from_name, to_name, amount)[1]
            if net:
                address = self.exchanges[to_name].fetch_deposit_address(asset)['address']
                self.exchanges[from_name].withdraw(asset, amount, address, net)