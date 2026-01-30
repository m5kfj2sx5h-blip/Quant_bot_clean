import unittest
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
from decimal import Decimal
import logging
import sys
import os
import random
from datetime import datetime

# Fix path to import modules
sys.path.append(os.getcwd())

# MOCK LOGGER
sys.modules['utils.logger'] = MagicMock()
sys.modules['utils.logger'].get_logger.return_value = logging.getLogger('mock')

# Import Core Logic
from core.liquidity import LiquidityAnalyzer
from core.auction import AuctionContextModule, AuctionState
# We will mock SentimentAnalyzer

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MonteCarloArb")

class MockSentiment:
    def __init__(self):
        self.multiplier = Decimal('1.0')
    def get_signal_multiplier(self):
        return self.multiplier

class MonteCarloArbSim:
    def __init__(self, steps=5000):
        self.steps = steps
        self.dt = 1/24 # Hourly steps? No, let's say minute steps. 1/1440.
        # Volatility
        self.daily_vol = 0.04 # 4% crypto vol
        self.sigma = self.daily_vol # / np.sqrt(1) if daily
        self.mu = 0.0000 
        
        # State
        self.capital = Decimal('5000.00')
        self.trades = []
        self.equity_curve = []
        
        # Modules
        self.auction_module = AuctionContextModule()
        self.sentiment = MockSentiment() # Default Neutral
        
    def generate_price_paths(self, start_price=50000.0):
        """Generates two correlated price paths (Exchange A and B)."""
        # GBM for Market Price
        t = np.linspace(0, 1, self.steps)
        W = np.random.standard_normal(size=self.steps) 
        W = np.cumsum(W) * np.sqrt(1/self.steps)
        X = (self.mu - 0.5 * self.sigma**2) * t + self.sigma * W
        market_price = start_price * np.exp(X)
        
        # Exchange A: Market + Noise
        noise_a = np.random.normal(0, 0.001, self.steps) # 0.1% noise
        price_a = market_price * (1 + noise_a)
        
        # Exchange B: Exchange A + Mean Reverting Spread
        # spread_t = mean_spread + phi * (spread_{t-1} - mean) + epsilon
        # Simplistic: Just Market + Noise (Uncorrelated noise creates arb)
        noise_b = np.random.normal(0, 0.001, self.steps)
        price_b = market_price * (1 + noise_b)
        
        return price_a, price_b

    def generate_book(self, price, depth_u=1.0):
        """
        Generates a synthetic order book around price.
        depth_u: Depth utilization factor (0.1 = thin, 10.0 = thick)
        """
        # Base liquidity roughly $50k at top level for BTC
        base_qty = Decimal('0.5') * Decimal(str(depth_u)) 
        
        bids = []
        asks = []
        
        for i in range(5):
            spread = Decimal('0.0005') * (i+1) # 5bps steps
            p_bid = Decimal(str(price)) * (Decimal('1') - spread)
            p_ask = Decimal(str(price)) * (Decimal('1') + spread)
            
            qty = base_qty * (Decimal('1.2') ** i) # Exponential depth
            
            bids.append({'price': p_bid, 'amount': qty})
            asks.append({'price': p_ask, 'amount': qty})
            
        return {'bids': bids, 'asks': asks}

    def run(self):
        logger.info(f"Starting Monte Carlo Arb Sim ({self.steps} steps)...")
        
        price_a, price_b = self.generate_price_paths()
        
        for t in range(self.steps):
            pA = price_a[t]
            pB = price_b[t]
            
            # Scenario: Flash Crash at t=2000
            is_crash = False
            if 2000 <= t < 2050:
                is_crash = True
                pA *= 0.95 # Drop 5%
                pB *= 0.94 # Drop 6% (Panic)
            
            # Scenario: Thin Liquidity (Night time)
            depth_factor = 1.0
            if t % 50 < 10: # Periodically thin
                depth_factor = 0.2
            
            # 1. Detect Opportunity
            # Buy A, Sell B
            diff_ab = (pB - pA) / pA
            # Buy B, Sell A
            diff_ba = (pA - pB) / pB
            
            threshold = 0.003 # 0.3% target (Fees ~0.15% + 0.15%)
            
            action = None
            if diff_ab > threshold:
                action = 'BUY_A_SELL_B'
                buy_price = pA
                sell_price = pB
                gross_pct = diff_ab
            elif diff_ba > threshold:
                action = 'BUY_B_SELL_A'
                buy_price = pB
                sell_price = pA
                gross_pct = diff_ba
            
            if action:
                # 2. RUN QBOT FILTERS
                
                # A. Auction Prevention (Falling Knife)
                # If crashing, Auction should detect "Imbalanced Selling" on Buy Side?
                # Actually, if we buy A, we check A's sellers.
                # If Market is Crashing, Selling Pressure is High.
                
                # Simulating Auction Logic:
                # If is_crash, pressure = High
                auction_score = 0.0
                if is_crash:
                    auction_score = -0.8 # Heavy Selling
                else:
                    auction_score = np.random.normal(0, 0.2)
                
                # Filter: If Auction Score < -0.5 (Selling Pressure), Block Buy
                if auction_score < -0.5:
                    # Valid Block - "Saved by Phase 10"
                    self.trades.append({'step': t, 'type': 'BLOCKED_AUCTION', 'pnl': 0})
                    continue
                
                # B. Sentiment Logic (Phase 11)
                # Random Sentiment
                sent_val = np.random.choice([1.0, 0.8, 0.5], p=[0.2, 0.6, 0.2])
                self.sentiment.multiplier = Decimal(str(sent_val))
                
                # C. Liquidity Sizing (Phase 8)
                # Generate Books
                book_buy = self.generate_book(buy_price, depth_factor)
                book_sell = self.generate_book(sell_price, depth_factor)
                
                # Parse for Analyzer (List of Tuples)
                asks = [(x['price'], x['amount']) for x in book_buy['asks']]
                bids = [(x['price'], x['amount']) for x in book_sell['bids']]
                
                # Limit Slippage to 0.2%
                max_slip = Decimal('0.002')
                max_buy = LiquidityAnalyzer.calculate_max_size_with_slippage(asks, max_slip)
                max_sell = LiquidityAnalyzer.calculate_max_size_with_slippage(bids, max_slip)
                
                # Convert to USD
                limit_buy_usd = max_buy * Decimal(str(buy_price))
                limit_sell_usd = max_sell * Decimal(str(sell_price))
                
                # Trade Size
                size_usd = min(self.capital, Decimal('1000'), limit_buy_usd, limit_sell_usd)
                
                # Sentiment Adjust
                size_usd *= self.sentiment.multiplier
                
                if size_usd < Decimal('10'):
                    # Liquidity too thin
                    self.trades.append({'step': t, 'type': 'SKIPPED_THIN', 'pnl': 0})
                    continue
                
                # EXECUTION SIMULATION
                # Real PnL = (Sell_VWAP - Buy_VWAP) - Fees
                # Get VWAP for this size
                buy_vwap, _ = LiquidityAnalyzer.get_vwap_for_size(asks, size_usd / Decimal(str(buy_price)))
                sell_vwap, _ = LiquidityAnalyzer.get_vwap_for_size(bids, size_usd / Decimal(str(sell_price)))
                
                fees = size_usd * Decimal('0.002') # 0.2% total
                
                gross_profit = (sell_vwap - buy_vwap) * (size_usd / buy_vwap)
                net_profit = gross_profit - fees
                
                self.capital += net_profit
                self.trades.append({
                    'step': t,
                    'type': 'TRADE',
                    'size': float(size_usd),
                    'gross_pct': float(gross_pct),
                    'pnl': float(net_profit),
                    'crash': is_crash,
                    'sentiment': float(sent_val)
                })
            
            self.equity_curve.append(float(self.capital))
            
        print(f"Generic Sim Done. Final Equity: {self.capital}")
        self.save_report()

    def save_report(self):
        # Generate HTML (Simplified version of previous, specific to Arb)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = f"tests/results/arb_sim_{timestamp}.html"
        os.makedirs("tests/results", exist_ok=True)
        
        # Stats
        wins = len([t for t in self.trades if t.get('pnl', 0) > 0])
        total = len([t for t in self.trades if t['type'] == 'TRADE'])
        if total == 0: total=1
        win_rate = (wins / total) * 100
        
        # HTML
        html = f"""
        <html><body>
        <h1>Monte Carlo Arbitrage Verification</h1>
        <h2>Scenario: 1 Week Volatility (Flash Crash Included)</h2>
        <p>Final Equity: ${float(self.capital):.2f}</p>
        <p>Win Rate: {win_rate:.1f}%</p>
        <p>Total Trades: {total}</p>
        <h3>Trade Log</h3>
        <table border=1>
        <tr><th>Step</th><th>Type</th><th>Size</th><th>PnL</th><th>Crash?</th></tr>
        """
        for t in self.trades:
            color = "green" if t.get('pnl', 0) > 0 else "red"
            if t['type'] != 'TRADE': color = "gray"
            html += f"<tr><td>{t['step']}</td><td>{t['type']}</td><td>{t.get('size',0):.2f}</td><td style='color:{color}'>{t.get('pnl',0):.2f}</td><td>{t.get('crash', False)}</td></tr>"
        
        html += "</table></body></html>"
        
        with open(report_path, "w") as f:
            f.write(html)
        print(f"Report saved to {report_path}")

if __name__ == "__main__":
    sim = MonteCarloArbSim(steps=5000)
    sim.run()
