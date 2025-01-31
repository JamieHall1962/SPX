import sqlite3
from datetime import datetime
import pytz
from dataclasses import asdict
from typing import Optional, Dict, Any

class TradeDatabase:
    def __init__(self, db_path="trades.db"):
        self.db_path = db_path
        self.setup_database()
    
    def setup_database(self):
        """Create the database tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Trade attempts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    trade_name TEXT NOT NULL,
                    config_type TEXT NOT NULL,
                    spx_price REAL,
                    short_dte INTEGER,
                    put_long_dte INTEGER,
                    call_long_dte INTEGER,
                    put_delta REAL,
                    call_delta REAL,
                    put_width INTEGER,
                    call_width INTEGER,
                    quantity INTEGER,
                    status TEXT NOT NULL,
                    reason_if_failed TEXT,
                    initial_debit REAL,
                    final_debit REAL,
                    fill_time TEXT,
                    order_id INTEGER
                )
            """)
            
            # Option legs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS option_legs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_attempt_id INTEGER,
                    leg_type TEXT NOT NULL,  -- short_put, long_put, short_call, long_call
                    contract_symbol TEXT NOT NULL,
                    strike REAL NOT NULL,
                    expiry TEXT NOT NULL,
                    delta REAL,
                    implied_vol REAL,
                    price REAL,
                    FOREIGN KEY (trade_attempt_id) REFERENCES trade_attempts (id)
                )
            """)
            
            # Price adjustments table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_adjustments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_attempt_id INTEGER,
                    adjustment_time TEXT NOT NULL,
                    old_debit REAL NOT NULL,
                    new_debit REAL NOT NULL,
                    adjustment_number INTEGER NOT NULL,
                    FOREIGN KEY (trade_attempt_id) REFERENCES trade_attempts (id)
                )
            """)
            
            conn.commit()
    
    def record_trade_attempt(self, config: Any, spx_price: float, status: str, 
                           reason_if_failed: Optional[str] = None,
                           initial_debit: Optional[float] = None,
                           final_debit: Optional[float] = None,
                           fill_time: Optional[str] = None,
                           order_id: Optional[int] = None) -> int:
        """Record a trade attempt in the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            now = datetime.now(pytz.timezone('US/Eastern')).isoformat()
            
            cursor.execute("""
                INSERT INTO trade_attempts (
                    timestamp, trade_name, config_type, spx_price,
                    short_dte, put_long_dte, call_long_dte,
                    put_delta, call_delta, put_width, call_width,
                    quantity, status, reason_if_failed,
                    initial_debit, final_debit, fill_time, order_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now, config.trade_name, config.trade_type, spx_price,
                config.short_dte, config.put_long_dte, config.call_long_dte,
                config.put_delta, config.call_delta, config.put_width, config.call_width,
                config.quantity, status, reason_if_failed,
                initial_debit, final_debit, fill_time, order_id
            ))
            
            return cursor.lastrowid
    
    def record_option_leg(self, trade_attempt_id: int, leg_type: str, option: Any):
        """Record an option leg for a trade attempt"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO option_legs (
                    trade_attempt_id, leg_type, contract_symbol,
                    strike, expiry, delta, implied_vol, price
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_attempt_id,
                leg_type,
                option.contract.localSymbol,
                option.contract.strike,
                option.contract.lastTradeDateOrContractMonth,
                getattr(option, 'delta', None),
                getattr(option, 'implied_vol', None),
                getattr(option, 'price', None)
            ))
    
    def record_price_adjustment(self, trade_attempt_id: int, old_debit: float, 
                              new_debit: float, adjustment_number: int):
        """Record a price adjustment for a trade attempt"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            now = datetime.now(pytz.timezone('US/Eastern')).isoformat()
            
            cursor.execute("""
                INSERT INTO price_adjustments (
                    trade_attempt_id, adjustment_time, old_debit,
                    new_debit, adjustment_number
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                trade_attempt_id,
                now,
                old_debit,
                new_debit,
                adjustment_number
            ))
    
    def get_trade_history(self, days: int = 30) -> list:
        """Get trade history for the last N days"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cutoff_date = (datetime.now(pytz.timezone('US/Eastern')) -
                          timedelta(days=days)).isoformat()
            
            cursor.execute("""
                SELECT * FROM trade_attempts
                WHERE timestamp > ?
                ORDER BY timestamp DESC
            """, (cutoff_date,))
            
            return cursor.fetchall()
    
    def get_unfilled_trades(self) -> list:
        """Get all trades that weren't filled"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM trade_attempts
                WHERE status = 'FAILED' OR status = 'NOT_FILLED'
                ORDER BY timestamp DESC
            """)
            
            return cursor.fetchall()
    
    def get_trade_details(self, trade_attempt_id: int) -> Dict[str, Any]:
        """Get complete details for a specific trade attempt"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get trade attempt details
            cursor.execute("SELECT * FROM trade_attempts WHERE id = ?", (trade_attempt_id,))
            trade = cursor.fetchone()
            
            if not trade:
                return None
                
            # Get option legs
            cursor.execute("SELECT * FROM option_legs WHERE trade_attempt_id = ?", 
                         (trade_attempt_id,))
            legs = cursor.fetchall()
            
            # Get price adjustments
            cursor.execute("SELECT * FROM price_adjustments WHERE trade_attempt_id = ?", 
                         (trade_attempt_id,))
            adjustments = cursor.fetchall()
            
            return {
                "trade": trade,
                "legs": legs,
                "adjustments": adjustments
            } 