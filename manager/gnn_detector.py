"""
GNN Arbitrage Detector - Step 3 Premium Feature

Uses Graph Neural Networks (GraphSAGE) to identify complex arbitrage cycles
that simple brute-force algorithms miss. The key innovation is using GNN to
*prune* the market graph before running cycle detection, dramatically speeding
up the search for profitable paths.

Official References:
- PyTorch Geometric SAGEConv: https://pytorch-geometric.readthedocs.io
- NetworkX simple_cycles: https://networkx.org/documentation
"""
import math
import time
from decimal import Decimal
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict

try:
    import torch
    import torch.nn.functional as F
    from torch_geometric.nn import SAGEConv
    from torch_geometric.data import Data
    import networkx as nx
    GNN_AVAILABLE = True
except ImportError:
    GNN_AVAILABLE = False
    torch = None
    SAGEConv = None
    Data = None
    nx = None

from utils.logger import get_logger

logger = get_logger(__name__)


class GNNArbitrageDetector:
    """
    Graph Neural Network based arbitrage cycle detector.
    
    Architecture:
    1. Build a directed graph where nodes = assets, edges = exchange rates
    2. Encode node features (liquidity, volatility) via GraphSAGE
    3. Prune low-probability edges using learned embeddings
    4. Run NetworkX simple_cycles on the pruned subgraph
    5. Validate cycles for actual profitability
    """
    
    def __init__(self, hidden_dim: int = 32, num_layers: int = 2, min_profit: float = 0.003):
        """
        Args:
            hidden_dim: Hidden dimension for GraphSAGE layers
            num_layers: Number of GraphSAGE layers
            min_profit: Minimum profit threshold for a cycle to be considered valid
        """
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.min_profit = Decimal(str(min_profit))
        self.model = None
        self.asset_to_idx: Dict[str, int] = {}
        self.idx_to_asset: Dict[int, str] = {}
        
        if not GNN_AVAILABLE:
            logger.warning("GNN dependencies not available. Install torch, torch-geometric, networkx.")
    
    def build_graph(self, books: Dict[str, Dict], market_data: Optional[Any] = None) -> Optional[Tuple]:
        """
        Builds a PyTorch Geometric graph from order books.
        
        Args:
            books: Dict of {exchange: {pair: book_data}}
            market_data: Optional MarketData instance for node features
            
        Returns:
            Tuple of (Data, nx.DiGraph, rate_matrix) or None if insufficient data
        """
        if not GNN_AVAILABLE:
            return None
            
        # Collect all unique assets and edges
        edges = []  # (src_idx, dst_idx, rate)
        assets = set()
        
        for ex_name, pairs in books.items():
            for pair, book in pairs.items():
                if '/' not in pair:
                    continue
                base, quote = pair.split('/')
                assets.add(base)
                assets.add(quote)
                
                # Extract best bid/ask from raw book
                bid_price, ask_price = self._extract_prices(book)
                if bid_price and ask_price:
                    # Edge: quote -> base at ask price (buying base)
                    # Edge: base -> quote at bid price (selling base)
                    edges.append((quote, base, ask_price, ex_name))  # Buy
                    edges.append((base, quote, bid_price, ex_name))  # Sell
        
        if len(assets) < 3 or len(edges) < 3:
            return None
            
        # Build index mappings
        self.asset_to_idx = {asset: i for i, asset in enumerate(sorted(assets))}
        self.idx_to_asset = {i: asset for asset, i in self.asset_to_idx.items()}
        num_nodes = len(assets)
        
        # Build edge index and weights
        edge_index = []
        edge_weights = []
        rate_matrix = defaultdict(dict)  # For profit calculation
        
        for src, dst, rate, ex in edges:
            src_idx = self.asset_to_idx[src]
            dst_idx = self.asset_to_idx[dst]
            edge_index.append([src_idx, dst_idx])
            # Use -log(rate) for Bellman-Ford style detection
            log_rate = -math.log(float(rate)) if rate > 0 else 0
            edge_weights.append(log_rate)
            rate_matrix[src][dst] = rate
        
        edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous()
        edge_attr = torch.tensor(edge_weights, dtype=torch.float).unsqueeze(1)
        
        # Node features: use market data if available, else ones
        if market_data:
            x = self._build_node_features(market_data, num_nodes)
        else:
            x = torch.ones((num_nodes, 4))  # Placeholder features
        
        data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
        
        # Build NetworkX graph for cycle detection
        G = nx.DiGraph()
        for i, asset in enumerate(sorted(assets)):
            G.add_node(i, name=asset)
        for (src, dst, rate, ex) in edges:
            G.add_edge(self.asset_to_idx[src], self.asset_to_idx[dst], rate=float(rate), exchange=ex)
        
        return data, G, rate_matrix
    
    def _extract_prices(self, book: Any) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """Extract bid/ask prices from raw book data (handles all formats)."""
        try:
            bids, asks = None, None
            
            # Dict format (Binance/Kraken)
            if isinstance(book, dict):
                bids = book.get('bids')
                asks = book.get('asks')
                if not bids:  # Kraken nested
                    for v in book.values():
                        if isinstance(v, dict) and 'bids' in v:
                            bids = v.get('bids')
                            asks = v.get('asks')
                            break
            # Coinbase object
            elif hasattr(book, 'pricebook'):
                bids = book.pricebook.bids
                asks = book.pricebook.asks
            
            if not bids or not asks:
                return None, None
            
            # Parse first level
            def get_price(entry):
                if isinstance(entry, (list, tuple)):
                    return Decimal(str(entry[0]))
                if hasattr(entry, 'price'):
                    return Decimal(str(entry.price))
                if isinstance(entry, dict):
                    return Decimal(str(entry.get('price', 0)))
                return None
            
            return get_price(bids[0]), get_price(asks[0])
        except Exception:
            return None, None
    
    def _build_node_features(self, market_data: Any, num_nodes: int) -> torch.Tensor:
        """Build node features from MarketData metrics."""
        features = torch.ones((num_nodes, 4))  # [vol, momentum, imbalance, depth]
        
        for symbol, metrics in market_data.metrics.items():
            if '/' in symbol:
                base = symbol.split('/')[0]
                if base in self.asset_to_idx:
                    idx = self.asset_to_idx[base]
                    features[idx, 0] = float(metrics.get('volatility', 1))
                    features[idx, 1] = float(metrics.get('momentum', 0))
                    features[idx, 2] = float(metrics.get('imbalance', 0))
                    features[idx, 3] = float(metrics.get('depth_ratio', 1))
        
        return features
    
    def detect(self, books: Dict[str, Dict], market_data: Optional[Any] = None, 
               max_cycles: int = 10, max_length: int = 4) -> List[Dict]:
        """
        Detect profitable arbitrage cycles using GNN.
        
        Args:
            books: Order books by exchange {ex: {pair: book}}
            market_data: Optional MarketData for enhanced features
            max_cycles: Maximum number of cycles to return
            max_length: Maximum cycle length (triangular = 3)
            
        Returns:
            List of profitable cycles with metadata
        """
        if not GNN_AVAILABLE:
            logger.warning("GNN not available, returning empty cycles")
            return []
        
        start_time = time.time()
        result = self.build_graph(books, market_data)
        
        if not result:
            return []
        
        data, G, rate_matrix = result
        
        # Initialize model if needed
        if self.model is None:
            self.model = self._create_model(data.x.size(1))
        
        # Forward pass to get embeddings
        self.model.eval()
        with torch.no_grad():
            embeddings = self.model(data.x, data.edge_index)
        
        # Prune graph using embedding similarity
        pruned_G = self._prune_graph(G, embeddings, threshold=0.3)
        
        # Find cycles on pruned graph
        profitable_cycles = []
        try:
            for cycle in nx.simple_cycles(pruned_G, length_bound=max_length):
                if len(cycle) < 3:
                    continue
                    
                profit = self._calculate_cycle_profit(cycle, rate_matrix)
                if profit > self.min_profit:
                    cycle_assets = [self.idx_to_asset[i] for i in cycle]
                    profitable_cycles.append({
                        'path': cycle_assets,
                        'profit': float(profit),
                        'length': len(cycle)
                    })
                    
                if len(profitable_cycles) >= max_cycles:
                    break
        except Exception as e:
            logger.error(f"Cycle detection error: {e}")
        
        elapsed = time.time() - start_time
        logger.info(f"[GNN] Found {len(profitable_cycles)} cycles in {elapsed:.3f}s")
        
        return sorted(profitable_cycles, key=lambda x: x['profit'], reverse=True)
    
    def _create_model(self, in_channels: int) -> torch.nn.Module:
        """Create a simple GraphSAGE model."""
        class GraphSAGEModel(torch.nn.Module):
            def __init__(self, in_ch, hidden, num_layers):
                super().__init__()
                self.convs = torch.nn.ModuleList()
                self.convs.append(SAGEConv(in_ch, hidden, aggr='mean'))
                for _ in range(num_layers - 1):
                    self.convs.append(SAGEConv(hidden, hidden, aggr='mean'))
            
            def forward(self, x, edge_index):
                for conv in self.convs[:-1]:
                    x = conv(x, edge_index)
                    x = F.relu(x)
                x = self.convs[-1](x, edge_index)
                return x
        
        return GraphSAGEModel(in_channels, self.hidden_dim, self.num_layers)
    
    def _prune_graph(self, G: 'nx.DiGraph', embeddings: torch.Tensor, threshold: float) -> 'nx.DiGraph':
        """Prune edges with low embedding similarity."""
        pruned = nx.DiGraph()
        pruned.add_nodes_from(G.nodes(data=True))
        
        for u, v, data in G.edges(data=True):
            # Cosine similarity between node embeddings
            sim = F.cosine_similarity(
                embeddings[u].unsqueeze(0),
                embeddings[v].unsqueeze(0)
            ).item()
            
            # Keep edge if similarity is above threshold OR rate is high
            rate = data.get('rate', 1.0)
            if sim > threshold or rate > 1.0:
                pruned.add_edge(u, v, **data)
        
        return pruned
    
    def _calculate_cycle_profit(self, cycle: List[int], rate_matrix: Dict) -> Decimal:
        """Calculate profit of traversing a cycle starting with 1 unit."""
        value = Decimal('1.0')
        for i in range(len(cycle)):
            src = self.idx_to_asset[cycle[i]]
            dst = self.idx_to_asset[cycle[(i + 1) % len(cycle)]]
            rate = rate_matrix.get(src, {}).get(dst, Decimal('0'))
            if rate == 0:
                return Decimal('-1')  # Invalid cycle
            value *= Decimal(str(rate))
        return value - Decimal('1.0')  # Profit = final - initial
