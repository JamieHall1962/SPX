from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict
import time
from threading import Thread
from config.trade_config import TradeConfig
from connection.tws_manager import ConnectionManager
from trading.executor import TradeExecutor
from trading.scheduler import TradeScheduler
from trading.option_finder import is_market_hours

@dataclass
class Position:
    """Represents an option position"""
    contract: any  # IB Contract
    quantity: int
    entry_price: float

@dataclass
class SystemStatus:
    """Encapsulates current system status for UI updates"""
    is_connected: bool
    market_open: bool
    spx_price: Optional[float]
    es_price: Optional[float]
    next_trade: Optional[dict]
    active_trades: Dict[str, 'ActiveTrade']

@dataclass
class ActiveTrade:
    """Represents a currently active trade"""
    config: TradeConfig
    entry_time: datetime
    positions: List[Position]
    current_status: dict  # Deltas, P&L, etc.

class TradingManager:
    """Manages all trading operations"""
    def __init__(self):
        self.connection_manager = None
        self.scheduler = None
        self.executor = None
        self.running = False
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.monitor_interval = 1  # seconds
        self.monitor_thread: Optional[Thread] = None
    
    def start(self) -> bool:
        """Initialize all trading components"""
        try:
            # Initialize components
            self.connection_manager = ConnectionManager()
            self.scheduler = TradeScheduler()
            self.executor = TradeExecutor(self.connection_manager)
            
            # Start monitoring loop in a separate thread
            self.running = True
            self.monitor_thread = Thread(target=self._monitoring_loop)
            self.monitor_thread.start()
            return True
            
        except Exception as e:
            print(f"Error starting trading system: {str(e)}")
            return False
    
    def stop(self):
        """Stop all trading operations"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        if self.connection_manager:
            self.connection_manager.disconnect()
    
    def _monitoring_loop(self):
        """Main monitoring loop that runs continuously while system is active"""
        while self.running:
            try:
                # 1. Check for new trades to enter
                next_trade = self.scheduler.get_next_trade()
                if next_trade and self._should_enter_trade(next_trade):
                    success = self.executor.execute_trade(next_trade.config)
                    if success:
                        self.active_trades[next_trade.name] = ActiveTrade(
                            config=next_trade.config,
                            entry_time=datetime.now(),
                            positions=self.executor.get_positions(),
                            current_status={}
                        )
                
                # 2. Monitor active trades
                for trade_id, trade in list(self.active_trades.items()):
                    # Update trade status (deltas, P&L, etc.)
                    trade.current_status = self._update_trade_status(trade)
                    
                    # Check exit conditions
                    if self._should_exit_trade(trade):
                        success = self.executor.exit_trade(trade)
                        if success:
                            del self.active_trades[trade_id]
                
                # 3. Update market data and status
                self.connection_manager.update_market_data()
                
                # 4. Sleep for monitoring interval
                time.sleep(self.monitor_interval)
                
            except Exception as e:
                print(f"Error in monitoring loop: {str(e)}")
                time.sleep(5)  # Add delay on error to prevent rapid retries
    
    def _should_enter_trade(self, trade) -> bool:
        """Check if we should enter a scheduled trade"""
        return (
            is_market_hours() and
            self._check_market_conditions(trade.config) and
            not self._has_conflicting_trades(trade.config)
        )
    
    def _check_market_conditions(self, config: TradeConfig) -> bool:
        """Check if market conditions are suitable for the trade"""
        # Implement market condition checks
        return True  # Placeholder
    
    def _has_conflicting_trades(self, config: TradeConfig) -> bool:
        """Check if there are any conflicting active trades"""
        # Implement conflict checking logic
        return False  # Placeholder
    
    def _update_trade_status(self, trade: ActiveTrade) -> dict:
        """Update status of an active trade"""
        # Implement status update logic
        return {}  # Placeholder
    
    def _is_exit_time_reached(self, exit_time: datetime, entry_time: datetime) -> bool:
        """Check if a time-based exit condition is met"""
        return datetime.now() >= exit_time
    
    def _should_exit_trade(self, trade: ActiveTrade) -> bool:
        """Check if a trade should be exited"""
        status = trade.current_status
        config = trade.config
        
        # Check each exit condition
        for condition, value in config.exit_conditions.items():
            if condition == "abs_delta_threshold":
                if abs(status.get("delta", 0)) > value:
                    return True
            elif condition == "profit_target":
                if status.get("pnl", 0) >= value:
                    return True
            # Add other exit condition checks
        
        # Check time-based exits
        for exit_time in config.time_based_exits:
            if self._is_exit_time_reached(exit_time, trade.entry_time):
                return True
        
        return False
    
    def get_status(self) -> SystemStatus:
        """Get current system status for UI updates"""
        if not self.connection_manager:
            return SystemStatus(
                is_connected=False,
                market_open=False,
                spx_price=None,
                es_price=None,
                next_trade=None,
                active_trades={}
            )
        
        return SystemStatus(
            is_connected=self.connection_manager.is_connected(),
            market_open=is_market_hours(),
            spx_price=self.connection_manager.get_spx_price(),
            es_price=self.connection_manager.get_es_price(),
            next_trade=self.scheduler.get_next_trade() if self.scheduler else None,
            active_trades=self.active_trades
        ) 