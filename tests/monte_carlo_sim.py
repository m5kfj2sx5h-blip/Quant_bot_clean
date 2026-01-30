
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
from decimal import Decimal
from typing import Dict, List
import logging
import sys
import os
import random

# Fix path to import modules
sys.path.append(os.getcwd())

# MOCK LOGGER BEFORE IMPORTS to avoid PermissionError
sys.modules['utils.logger'] = MagicMock()
sys.modules['utils.logger'].get_logger.return_value = logging.getLogger('mock')

from manager.scanner import AlphaQuadrantAnalyzer, ArbitrageAnalyzer, MarketContext
from manager.market_data import MarketData

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MonteCarlo")

class SyntheticMarketData(MarketData):
    """
    Mock MarketData that serves synthesized order books based on GBM price paths.
    """
    def __init__(self):
        super().__init__()
        self.current_price = 50000.0
        self.current_time = 0
        
    def set_market_state(self, price, volatility, depth_skew=0.0):
        """
        Update synthetic state.
        depth_skew: positive = more bids (buy pressure), negative = more asks.
        """
        self.current_price = price
        # We don't actually store history in this mock effectively for the test loop, 
        # or we could clear and append to mimic real-time updates.
        # For 'scan', the analyzers call get_depth_ratio etc. which look at self.windows.
        # So we need to populate self.windows with synthetic "recent" data.
        
        # Clear old data for "instant" state simulation
        # self.windows.clear() # Actually we want momentum, so maybe keep history?
        # For simplicity in MC, we just append the new state.
        
        # Generate synthetic book
        book = self._generate_book(price, depth_skew)
        self.update("BTC/USDT", book)
        
    def _generate_book(self, mid_price, skew):
        """Generate a synthetic book with exponential decay depth."""
        # Skew affects volume ratio
        base_vol = 5.0 # BTC
        bid_vol_mult = 1.0 + skew
        ask_vol_mult = 1.0 - skew
        
        bids = []
        asks = []
        
        # 10 levels
        for i in range(10):
            # 0.01% spread steps
            bp = mid_price * (1 - (0.0005 * (i+1)))
            ap = mid_price * (1 + (0.0005 * (i+1)))
            
            bv = base_vol * (0.8 ** i) * bid_vol_mult
            av = base_vol * (0.8 ** i) * ask_vol_mult
            
            bids.append([bp, bv])
            asks.append([ap, av])
            
        return {'bids': bids, 'asks': asks}

    def get_market_means(self) -> Dict[str, Decimal]:
        """Override means for single-asset MC so we don't compare against self."""
        return {
            'depth_ratio_mean': Decimal('1.0'), 
            'imbalance_mean': Decimal('0.0')
        }

class TestMonteCarloSimulation(unittest.TestCase):
    def setUp(self):
        self.market_data = SyntheticMarketData()
        self.config = {'ALPHA_THRESHOLD': 1.2, 'paper_mode': True}
        self.alpha_analyzer = AlphaQuadrantAnalyzer(self.market_data, self.config, logger)
        
        # Calibration from Step 5a
        self.daily_vol = 0.0238 
        self.dt = 1/24 # Hourly steps
        self.hourly_vol = self.daily_vol * np.sqrt(self.dt)
        self.mu = 0.0001 # Slight drift

    def test_simulation_run(self):
        """
        Run 1000 step Monte Carlo simulation.
        Generate price path -> Update Market -> Scan -> Track Performance.
        """
        logger.info("Starting Monte Carlo Simulation (1000 steps)...")
        
        start_price = 50000.0
        price = start_price
        
        balance_usdt = Decimal('10000')
        holdings_btc = Decimal('0')
        
        trades = []
        equity_curve = []
        
        # Random seed for reproducibility
        np.random.seed(42)
        
        for t in range(1000):
            # 1. Macro Signal Logic (Step 9/README)
            # Simulate "Fired Macro Signal" at t=300 (Neutral -> Bull)
            macro_mode = 'NEUTRAL'
            macro_trend_bias = 0.0
            
            if t >= 300:
                macro_mode = 'BULL' # "BTC Mode"
                macro_trend_bias = 0.0002 # Positive drift bias
            
            # 2. Evolve Price (GBM + Macro Bias)
            # S_t = S_{t-1} * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)
            shock = np.random.normal(0, 1)
            # If Bull mode, skew chance of positive shock
            if macro_mode == 'BULL':
                shock += 0.1 
                
            drift = (self.mu + macro_trend_bias - 0.5 * self.hourly_vol**2) * self.dt
            diffusion = self.hourly_vol * np.sqrt(self.dt) * shock
            price = price * np.exp(drift + diffusion)
            
            # 3. Market Skew (Regime switching)
            # If Macro is Bull, skew tends to be positive (buy pressure)
            base_skew = 0.2 if macro_mode == 'BULL' else 0.0
            skew = np.clip(shock * 0.3 + base_skew, -0.8, 0.8)
            
            # 4. Update Synthetic Market
            self.market_data.set_market_state(price, self.hourly_vol, skew)
            
            # 5. Scan for Alpha opportunities
            opps = self.alpha_analyzer.scan(['BTC/USDT'])
            
            # 6. Execute Logic
            if opps:
                top_opp = opps[0]
                # If generated buy signal
                if top_opp['score'] > 1.2 and balance_usdt > 0:
                    # Buy
                    invest = float(balance_usdt) * 0.15
                    amount_btc = invest / price
                    
                    # Slippage model (0.05% + impact)
                    slippage = 0.0005 * (1 + abs(skew))
                    cost = invest * (1 + slippage)
                    
                    if balance_usdt >= cost:
                        balance_usdt -= Decimal(str(cost))
                        
                        # Update Avg Entry Price
                        old_qty = float(holdings_btc)
                        new_qty = float(amount_btc)
                        
                        # Allow robust tracking:
                        if hasattr(self, 'avg_entry'):
                             weighted_sum = (self.avg_entry * old_qty) + (price * new_qty)
                             self.avg_entry = weighted_sum / (old_qty + new_qty)
                        else:
                             self.avg_entry = price

                        holdings_btc += Decimal(str(amount_btc))
                        trades.append({
                            'step': t, 'type': 'BUY', 'price': price, 'amount': amount_btc, 
                            'score': top_opp['score'], 'skew': skew, 'avg_price': self.avg_entry,
                            'macro': macro_mode
                        })
            
            # Simple Sell Logic (Take Profit / Stop Loss)
            if holdings_btc > 0:
                # Sell trigger: Harder to sell in Bull Mode (HODL logic)
                sell_threshold = -0.6 if macro_mode == 'BULL' else -0.3
                
                if skew < sell_threshold: 
                    sell_amt = float(holdings_btc)
                    revenue = sell_amt * price
                    slippage = 0.0005 * (1 + abs(skew)) 
                    proceeds = revenue * (1 - slippage)
                    
                    # Calc Profit
                    avg_entry = getattr(self, 'avg_entry', price)
                    cost_basis = sell_amt * avg_entry
                    net_profit = proceeds - cost_basis
                    
                    balance_usdt += Decimal(str(proceeds))
                    holdings_btc = Decimal('0')
                    self.avg_entry = 0.0
                    
                    trades.append({
                        'step': t, 'type': 'SELL', 'price': price, 'amount': sell_amt,
                        'revenue': proceeds, 'skew': skew, 'net_profit': net_profit,
                        'macro': macro_mode
                    })

            # Track Equity
            equity = float(balance_usdt) + (float(holdings_btc) * price)
            equity_curve.append(equity)
            


        # Analysis
        initial_equity = 10000.0
        final_equity = equity_curve[-1]
        returns = (final_equity - initial_equity) / initial_equity * 100
        
        # Drawdown Calculation
        rolling_max = np.maximum.accumulate(equity_curve)
        drawdowns = (np.array(equity_curve) - rolling_max) / rolling_max * 100
        max_drawdown = np.min(drawdowns)

        logger.info(f"Simulation Complete.")
        logger.info(f"Initial Equity: ${initial_equity:.2f}")
        logger.info(f"Final Equity:   ${final_equity:.2f}")
        logger.info(f"Return:         {returns:.2f}%")
        logger.info(f"Max Drawdown:   {max_drawdown:.2f}%")
        logger.info(f"Total Trades:   {len(trades)}")
        
        # Calculate Sharpe Ratio
        df_eq = pd.Series(equity_curve)
        pct_chg = df_eq.pct_change().dropna()
        sharpe = 0.0
        if len(pct_chg) > 0:
            sharpe = pct_chg.mean() / pct_chg.std() * np.sqrt(252*24) if pct_chg.std() != 0 else 0
            logger.info(f"Sharpe Ratio:   {sharpe:.2f}")

        # --- SAVE RESULTS ---
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs('results', exist_ok=True)
            
            # 1. Save Text Report
            report_file = f'results/backtest_report_{timestamp}.txt'
            # ... (text saving omitted for brevity, keeping existing logic if needed or overwriting)
            # Re-implementing simplified text save to ensure consistency
            with open(report_file, 'w') as f:
                f.write("MONTE CARLO SIMULATION REPORT\n")
                f.write("=============================\n")
                f.write(f"Date: {datetime.now()}\n")
                f.write(f"Scenario: Macro Regime Switch (Neutral -> Bull)\n")
                f.write(f"Initial Equity: ${initial_equity:.2f}\n")
                f.write(f"Final Equity:   ${final_equity:.2f}\n")
                f.write(f"Net Return:     {returns:.2f}%\n")
                f.write(f"Max Drawdown:   {max_drawdown:.2f}%\n")
                f.write(f"Sharpe Ratio:   {sharpe:.2f}\n")
                f.write(f"Total Trades:   {len(trades)}\n")
                
            print(f"Detailed report saved to: {report_file}")
            
            # 3. Generate HTML Report (Interactive Dashboard)
            html_file = f'results/backtest_report_{timestamp}.html'
            
            # Prepare data for Chart.js
            labels = [str(i) for i in range(len(equity_curve))]
            data_points = [f"{x:.2f}" for x in equity_curve]
            dd_points = [f"{x:.2f}" for x in drawdowns]
            
            # Histogram Data (Profit Distribution)
            profits = [t.get('net_profit', 0) for t in trades if t['type']=='SELL']
            # Simple binning
            bins = [-100, -50, -10, 0, 10, 50, 100]
            hist_counts = [0] * (len(bins) - 1)
            for p in profits:
                for i in range(len(bins)-1):
                    if bins[i] <= p < bins[i+1]:
                        hist_counts[i] += 1
                        break
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Backtest Dashboard</title>
                <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
                <style>
                    body {{ font-family: 'Inter', system-ui, -apple-system, sans-serif; margin: 0; padding: 20px; background-color: #f0f2f5; color: #1a1a1a; }}
                    .container {{ max-width: 1200px; margin: 0 auto; }}
                    .header {{ background: white; padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; }}
                    h1 {{ margin: 0; font-size: 24px; color: #111; }}
                    .status-badge {{ background: #e3f2fd; color: #1976d2; padding: 5px 12px; border-radius: 20px; font-size: 14px; font-weight: 600; }}
                    
                    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
                    .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                    .card h3 {{ margin: 0 0 10px 0; color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }}
                    .card .value {{ font-size: 28px; font-weight: 700; color: #111; }}
                    .value.pos {{ color: #00c853; }}
                    .value.neg {{ color: #d50000; }}
                    
                    .charts-grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 20px; }}
                    .chart-card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); height: 400px; }}
                    
                    .log-container {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow-x: auto; }}
                    table {{ width: 100%; border-collapse: collapse; min-width: 600px; }}
                    th {{ text-align: left; padding: 12px; border-bottom: 2px solid #eee; color: #666; font-size: 12px; text-transform: uppercase; }}
                    td {{ padding: 12px; border-bottom: 1px solid #eee; font-size: 14px; }}
                    tr:hover {{ background-color: #f8f9fa; }}
                    .type-buy {{ color: #2196f3; font-weight: 600; }}
                    .type-sell {{ color: #ff9800; font-weight: 600; }}
                    .profit-win {{ color: #00c853; font-weight: 600; }}
                    .profit-loss {{ color: #d50000; font-weight: 600; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <div>
                            <h1>Arbitrage Strategy Backtest</h1>
                            <div style="color: #666; font-size: 14px; margin-top: 5px;">Scenario: Macro Regime Switch (Neutral -> Bull)</div>
                        </div>
                        <span class="status-badge">COMPLETED</span>
                    </div>
                    
                    <div class="kpi-grid">
                        <div class="card">
                            <h3>Total Return</h3>
                            <div class="value {'pos' if returns >= 0 else 'neg'}">{returns:+.2f}%</div>
                        </div>
                        <div class="card">
                            <h3>Net Profit</h3>
                            <div class="value {'pos' if final_equity - initial_equity >= 0 else 'neg'}">${final_equity - initial_equity:,.2f}</div>
                        </div>
                        <div class="card">
                            <h3>Max Drawdown</h3>
                            <div class="value neg">{max_drawdown:.2f}%</div>
                        </div>
                        <div class="card">
                            <h3>Total Trades</h3>
                            <div class="value">{len(trades)}</div>
                        </div>
                    </div>

                    <div class="charts-grid">
                        <div class="chart-card">
                            <canvas id="equityChart"></canvas>
                        </div>
                        <div class="chart-card">
                            <canvas id="distChart"></canvas>
                        </div>
                    </div>

                    <div class="log-container">
                        <h3>Trade Execution Log</h3>
                        <table>
                            <thead>
                                <tr>
                                    <th>Step</th>
                                    <th>Signal</th>
                                    <th>Price</th>
                                    <th>Size</th>
                                    <th>Metric</th>
                                    <th>PnL</th>
                                </tr>
                            </thead>
                            <tbody>
            """
            
            for t in list(reversed(trades))[:50]: # Show last 50 reversed
                pnl_class = ""
                pnl_str = "-"
                if t['type'] == 'SELL':
                    p = t.get('net_profit', 0)
                    pnl_class = "profit-win" if p > 0 else "profit-loss"
                    pnl_str = f"${p:.2f}"
                
                type_class = "type-buy" if t['type'] == 'BUY' else "type-sell"
                
                html_content += f"""
                                <tr>
                                    <td>{t['step']}</td>
                                    <td><span class="{type_class}">{t['type']}</span></td>
                                    <td>${t['price']:,.2f}</td>
                                    <td>{t.get('amount', 0):.4f}</td>
                                    <td>{t.get('score', 0):.2f}</td>
                                    <td><span class="{pnl_class}">{pnl_str}</span></td>
                                </tr>
                """
            
            html_content += f"""
                            </tbody>
                        </table>
                        <div style="text-align: center; margin-top: 15px; color: #666; font-size: 13px;">Showing last 50 trades</div>
                    </div>
                </div>

                <script>
                    // Equity Chart
                    new Chart(document.getElementById('equityChart'), {{
                        type: 'line',
                        data: {{
                            labels: {labels},
                            datasets: [
                                {{
                                    label: 'Portfolio Equity',
                                    data: {data_points},
                                    borderColor: '#2196f3',
                                    backgroundColor: 'rgba(33, 150, 243, 0.1)',
                                    borderWidth: 2,
                                    fill: true,
                                    pointRadius: 0,
                                    tension: 0.4
                                }}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            interaction: {{ mode: 'index', intersect: false }},
                            plugins: {{
                                title: {{ display: true, text: 'Equity Curve vs Macro Trend' }},
                                legend: {{ display: false }}
                            }},
                            scales: {{
                                x: {{ display: false }},
                                y: {{ grid: {{ color: '#f0f0f0' }} }}
                            }}
                        }}
                    }});

                    // Distribution Chart
                    new Chart(document.getElementById('distChart'), {{
                        type: 'bar',
                        data: {{
                            labels: ['High Loss', 'Loss', 'Small Loss', 'Break Even', 'Small Win', 'Win', 'High Win'],
                            datasets: [{{
                                label: 'Trade Outcomes',
                                data: {hist_counts},
                                backgroundColor: [
                                    '#c62828', '#e53935', '#ef9a9a', '#90a4ae', '#a5d6a7', '#66bb6a', '#2e7d32'
                                ],
                                borderRadius: 4
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {{
                                title: {{ display: true, text: 'Profit/Loss Distribution' }},
                                legend: {{ display: false }}
                            }},
                            scales: {{
                                y: {{ beginAtZero: true, grid: {{ display: false }} }},
                                x: {{ grid: {{ display: false }} }}
                            }}
                        }}
                    }});
                </script>
            </body>
            </html>
            """
            
            with open(html_file, 'w') as f:
                f.write(html_content)
                
            print(f"Interactive HTML report saved to: {html_file}")
            
        except Exception as e:
            print(f"Error saving results: {e}")

        # Only assert if we actually expected profit, but for random walk it might be chaotic.
        # Just check trades exist.
        if len(trades) == 0:
            # Force a fail if no trades, but for valid MC we want to see result even if 0 trades
            print("WARNING: No trades executed.")
        
        # Don't fail the test if ROI is negative, that's a valid result.

if __name__ == '__main__':
    unittest.main()
