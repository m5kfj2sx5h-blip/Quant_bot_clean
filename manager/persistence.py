import sqlite3
import logging
from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class PersistenceManager:
    def __init__(self, db_path: str = "logs/quant_bot.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path, timeout=30.0)

    def _init_db(self):
        with self._get_connection() as conn:
            # Enable WAL mode for concurrency (Reader doesn't block Writer)
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()
            
            # 1. Trades Table (Historical records)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    trade_type TEXT, -- ARB_CROSS, ARB_TRI, SNIPER, GOLD
                    buy_exchange TEXT,
                    sell_exchange TEXT,
                    buy_price TEXT,
                    sell_price TEXT,
                    amount TEXT,
                    fee_usd TEXT,
                    net_profit_usd TEXT,
                    execution_time_ms REAL
                )
            """)

            # 2. Portfolio State (Snapshots)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_value_usd TEXT,
                    total_profit_usd TEXT,
                    total_trades INTEGER,
                    winning_trades INTEGER,
                    snapshot_tpv_at_signal TEXT,
                    gold_accumulated_cycle TEXT,
                    gold_target_cycle TEXT,
                    current_mode TEXT,
                    exchange_balances TEXT -- JSON string
                )
            """)

            # 5. Dashboard Commands
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT,
                    params TEXT, -- JSON string
                    status TEXT DEFAULT 'PENDING',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. Active Positions (A-Bot & G-Bot state)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_positions (
                    symbol TEXT PRIMARY KEY,
                    exchange TEXT,
                    amount TEXT,
                    buy_price TEXT,
                    staked INTEGER, -- 0 or 1
                    is_seat_warmer INTEGER, -- 0 or 1
                    timestamp DATETIME
                )
            """)

            # 4. Market Snapshots (Price feed cache)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    exchange TEXT,
                    symbol TEXT,
                    bid TEXT,
                    ask TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (exchange, symbol)
                )
            """)
            
            # 6. Scan Audit (Real-time Scan Intelligence)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    scan_type TEXT, -- CROSS or TRI
                    pairs_scanned INTEGER,
                    opportunities_found INTEGER,
                    top_opportunity TEXT, -- JSON string
                    rejection_reason TEXT -- JSON string (summary of rejections)
                )
            """)

            # 7. Market Metrics (Rolling Stats Persistence)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    exchange TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    volatility REAL,
                    imbalance REAL,
                    sentiment REAL,
                    phase TEXT,
                    whale_score REAL,
                    FOREIGN KEY(symbol) REFERENCES trades(symbol)
                )
            """)
            
            conn.commit()
            logger.info(f"🗄️ SQLite Database initialized at {self.db_path}")

    def save_trade(self, trade_data: Dict[str, Any]):
        """Persist a trade for historical tracking and tax reporting."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades (
                    symbol, trade_type, buy_exchange, sell_exchange, 
                    buy_price, sell_price, amount, fee_usd, net_profit_usd, execution_time_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data.get('symbol'),
                trade_data.get('type'),
                trade_data.get('buy_exchange'),
                trade_data.get('sell_exchange'),
                str(trade_data.get('buy_price', '0')),
                str(trade_data.get('sell_price', '0')),
                str(trade_data.get('amount', '0')),
                str(trade_data.get('fee_usd', '0')),
                str(trade_data.get('net_profit_usd', '0')),
                trade_data.get('execution_time_ms', 0)
            ))
            conn.commit()

    def update_portfolio_state(self, portfolio: Any, current_mode: str):
        """Save a snapshot of the portfolio state."""
        import json
        
        # Serialize exchange balances to JSON
        balances_dict = {}
        for ex, assets in portfolio.exchange_balances.items():
            balances_dict[ex] = {asset: str(bal.total) for asset, bal in assets.items()}
            
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO portfolio_state (
                    total_value_usd, total_profit_usd, total_trades, winning_trades,
                    snapshot_tpv_at_signal, gold_accumulated_cycle, gold_target_cycle, 
                    current_mode, exchange_balances
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(portfolio.total_value_usd),
                str(portfolio.total_profit_usd),
                portfolio.total_trades,
                portfolio.winning_trades,
                str(portfolio.snapshot_tpv_at_signal),
                str(portfolio.gold_accumulated_this_cycle),
                str(portfolio.gold_target_this_cycle),
                current_mode,
                json.dumps(balances_dict)
            ))
            conn.commit()

    def save_market_snapshot(self, exchange: str, symbol: str, bid: Decimal, ask: Decimal):
        """Update the latest price snapshot for an exchange/symbol."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO market_snapshots (exchange, symbol, bid, ask, timestamp)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (exchange, symbol, str(bid), str(ask)))
            conn.commit()

    def get_market_snapshots(self) -> List[Dict[str, Any]]:
        """Fetch all latest price snapshots."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM market_snapshots")
            return [dict(row) for row in cursor.fetchall()]

    def save_command(self, command: str, params: Dict = None):
        """Save a manual command from the dashboard."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO commands (command, params) VALUES (?, ?)", 
                          (command, json.dumps(params or {})))
            conn.commit()

    def get_pending_commands(self) -> List[Dict[str, Any]]:
        """Fetch all pending commands."""
        import json
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM commands WHERE status = 'PENDING'")
            commands = []
            rows = cursor.fetchall()
            for row in rows:
                cmd = dict(row)
                cmd['params'] = json.loads(cmd['params'])
                commands.append(cmd)
            
            # Mark as processing
            if commands:
                ids = [str(c['id']) for c in commands]
                cursor.execute(f"UPDATE commands SET status = 'PROCESSING' WHERE id IN ({','.join(ids)})")
                conn.commit()
            return commands

    def mark_command_complete(self, command_id: int):
        """Mark a command as completed."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE commands SET status = 'COMPLETED' WHERE id = ?", (command_id,))
            conn.commit()

    def save_position(self, coin: str, pos_data: Dict[str, Any]):
        """Save an active position for A-Bot/G-Bot recovery."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO active_positions (
                    symbol, exchange, amount, buy_price, staked, is_seat_warmer, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                coin,
                pos_data.get('exchange'),
                str(pos_data.get('amount')),
                str(pos_data.get('buy_price')),
                1 if pos_data.get('staked') else 0,
                1 if pos_data.get('is_seat_warmer') else 0,
                pos_data.get('timestamp', datetime.now()).isoformat()
            ))
            conn.commit()

    def remove_position(self, coin: str):
        """Remove a position after it has been sold."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM active_positions WHERE symbol = ?", (coin,))
            conn.commit()

    def load_last_state(self) -> Optional[Dict[str, Any]]:
        """Load the most recent portfolio state snapshot."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM portfolio_state ORDER BY timestamp DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def load_active_positions(self) -> Dict[str, Any]:
        """Recover all active positions on startup."""
        positions = {}
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM active_positions")
            for row in cursor.fetchall():
                positions[row['symbol']] = {
                    'exchange': row['exchange'],
                    'amount': Decimal(row['amount']),
                    'buy_price': Decimal(row['buy_price']),
                    'staked': bool(row['staked']),
                    'is_seat_warmer': bool(row['is_seat_warmer']),
                    'timestamp': datetime.fromisoformat(row['timestamp'])
                }
        return positions

    def get_sweeps_count(self, month_str: str) -> int:
        """Count gold sweeps for a specific month (format: YYYY-MM)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # SQLite strftime or just string comparison on timestamp
            cursor.execute("""
                SELECT COUNT(*) FROM trades 
                WHERE trade_type = 'GOLD_SWEEP' 
                AND strftime('%Y-%m', timestamp) = ?
            """, (month_str,))
            return cursor.fetchone()[0]

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch latest trades for dashboard."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_all_pnl(self) -> List[Decimal]:
        """Fetch all P&L values for Sharpe calculation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT net_profit_usd FROM trades WHERE net_profit_usd IS NOT NULL")
            return [Decimal(row[0]) for row in cursor.fetchall()]

    def save_scan_audit(self, scan_data: Dict[str, Any]):
        """Save the result of a scan cycle."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO scan_audit (
                    scan_type, pairs_scanned, opportunities_found, top_opportunity, rejection_reason
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                scan_data.get('scan_type', 'CROSS'),
                scan_data.get('pairs_scanned', 0),
                scan_data.get('opportunities_found', 0),
                json.dumps(scan_data.get('top_opportunity', {})),
                json.dumps(scan_data.get('rejection_reason', {}))
            ))
            conn.commit()

    def get_latest_scan_audit(self) -> Optional[Dict[str, Any]]:
        """Get the most recent scan audit for the dashboard."""
        import json
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scan_audit ORDER BY timestamp DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                data = dict(row)
                data['top_opportunity'] = json.loads(data['top_opportunity'])
                data['rejection_reason'] = json.loads(data['rejection_reason'])
                return data
        return None

    def save_market_metrics(self, metrics: Dict[str, Any]):
        """Save detailed market metrics (volatility, imbalance, etc)."""
        if not metrics:
            return
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO market_metrics (
                    symbol, exchange, volatility, imbalance, sentiment, phase, whale_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.get('symbol'),
                metrics.get('exchange', 'aggregated'),
                metrics.get('volatility', 0.0),
                metrics.get('imbalance', 0.0),
                metrics.get('sentiment', 0.0),
                metrics.get('phase', 'UNKNOWN'),
                metrics.get('whale_score', 0.0)
            ))
            conn.commit()

    def get_latest_market_metrics(self, symbol: str = None) -> List[Dict[str, Any]]:
        """Get latest market metrics, optionally filtered by symbol."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if symbol:
                cursor.execute("""
                    SELECT * FROM market_metrics 
                    WHERE symbol = ? 
                    ORDER BY timestamp DESC LIMIT 1
                """, (symbol,))
            else:
                # Get latest for each symbol (simulated via group by or simple limit)
                # For dashboard overview, just getting recent 50 is fine
                cursor.execute("""
                    SELECT * FROM market_metrics 
                    ORDER BY timestamp DESC LIMIT 50
                """)
                
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
