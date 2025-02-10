from dataclasses import dataclass
from datetime import datetime, time as datetime_time
from typing import Optional, List, Dict, Any
import time
from threading import Thread
from config.trade_config import TradeConfig, DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3, DC_CONFIG_4, DC_CONFIG_5, DC_CONFIG_6, IC_CONFIG
from connection.tws_manager import ConnectionManager, OptionPosition
from trading.executor import TradeExecutor
from trading.scheduler import TradeScheduler
from utils.market_utils import is_market_hours
import pytz
from ibapi.contract import Contract
from ibapi.order import Order
from trading.option_finder import find_target_delta_option, get_expiry_from_dte
from trading.risk_monitor import RiskMonitor, RiskThresholds
import threading

@dataclass
class Position:
    """Represents an option position"""
    contract: any  # IB Contract
    quantity: int
    entry_price: float

@dataclass
class SystemStatus:
    """Current system status"""
    is_connected: bool
    market_open: bool
    spx_price: Optional[float]
    es_price: Optional[float]
    next_trade: Optional[Dict[str, Any]]
    active_trades: list

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
        self.connection_manager = ConnectionManager()
        self.executor = TradeExecutor(self.connection_manager)  # Create executor first
        self.scheduler = TradeScheduler(self.executor)    # Pass executor to scheduler
        self.active_trades = []
        self.running = False
        self.risk_monitor = RiskMonitor()
        
        # Initialize all trade configurations
        self.trade_configs = {
            # Friday DCs
            "DC_Friday_1015": DC_CONFIG,
            "DC_Friday_1155": DC_CONFIG_2,
            "DC_Friday_1300": DC_CONFIG_3,
            "DC_Friday_1410": DC_CONFIG_4,
            
            # Monday DCs
            "DC_Monday_1200": DC_CONFIG_5,
            "DC_Monday_1330": DC_CONFIG_6,
            
            # Thursday IC
            "IC_Thursday_1545": IC_CONFIG
        }
        
        # Add risk callback
        self.risk_monitor.add_risk_callback(self.handle_risk_event)
    
    def start(self) -> bool:
        """Start the trading system"""
        print("Starting trading system...")
        try:
            # Connect to TWS
            if not self.connection_manager.connect():
                print("Failed to connect to TWS")
                return False
            
            self.running = True
            
            # Start position monitoring in a separate thread
            self.monitor_thread = threading.Thread(target=self.monitor_positions)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            print("Trading system startup complete")
            return True
            
        except Exception as e:
            print(f"Error starting trading system: {e}")
            return False
    
    def stop(self):
        """Stop the trading system"""
        print("Stopping trading system...")
        self.running = False
        if hasattr(self, 'monitor_thread'):
            self.monitor_thread.join(timeout=5)
        self.connection_manager.disconnect()
        print("Trading system stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop that runs continuously while system is active"""
        while self.running:
            try:
                # 1. Check for new trades to enter
                next_trade = self.get_next_trade()
                if next_trade and self._should_enter_trade(next_trade):
                    success = self.executor.execute_trade(next_trade.config)
                    if success:
                        self.active_trades.append(ActiveTrade(
                            config=next_trade.config,
                            entry_time=datetime.now(),
                            positions=self.executor.get_positions(),
                            current_status={}
                        ))
                
                # 2. Monitor active trades
                for trade in self.active_trades:
                    # Update trade status (deltas, P&L, etc.)
                    trade.current_status = self._update_trade_status(trade)
                    
                    # Check exit conditions
                    if self._should_exit_trade(trade):
                        success = self.executor.exit_trade(trade)
                        if success:
                            self.active_trades.remove(trade)
                
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
    
    def get_status(self) -> Dict[str, Any]:
        """Get trading system status"""
        status = self.connection_manager.get_status()
        status.update({
            "running": self.running,
            "active_trades": len(self.active_trades)
        })
        return status
    
    def get_next_trade(self) -> Optional[Dict]:
        """Get the next scheduled trade"""
        if not self.scheduler:
            return None
            
        et_timezone = pytz.timezone('US/Eastern')
        current_time = datetime.now(et_timezone)
        current_day = current_time.strftime("%A")
        
        for trade in self.scheduler:
            if current_day in trade["days"]:
                trade_time = trade["time"]
                if current_time.time() < trade_time:
                    return {
                        "name": trade["name"],
                        "time": trade_time.strftime("%H:%M")
                    }
        
        # Check next day's trades
        next_day_trades = [t for t in self.scheduler if "Monday" in t["days"]]
        if next_day_trades:
            return {
                "name": next_day_trades[0]["name"],
                "time": next_day_trades[0]["time"].strftime("%H:%M")
            }
            
        return None

    def get_current_position(self) -> Optional[OptionPosition]:
        """Get current DC position if any"""
        positions = self.connection_manager.wrapper.positions
        
        # Look for today's DC position
        expiry = get_expiry_from_dte(0)
        for key, pos in positions.items():
            if (pos.contract.lastTradeDateOrContractMonth == expiry and 
                pos.contract.right == "P"):
                return pos
        return None

    def execute_trade(self, trade_config: TradeConfig) -> bool:
        """Execute a specific trade configuration"""
        try:
            print(f"Executing {trade_config.trade_name}")
            
            # Check if we already have a position for today
            current_position = self.get_current_position()
            if current_position:
                print(f"Already have position for today: {current_position.position} contracts")
                return False
            
            # Get current market price
            spx_price = self.connection_manager.get_spx_price()
            if not spx_price:
                print("Error: SPX price not available")
                return False
            
            contracts = []
            orders = []
            
            # Process each leg
            for leg in trade_config.legs:
                # Find expiry based on DTE
                expiry = get_expiry_from_dte(leg.dte)
                
                # For short legs, find appropriate strike based on delta
                if leg.position == -1:
                    option = find_target_delta_option(
                        self.connection_manager,
                        expiry=expiry,
                        right=leg.leg_type,
                        target_delta=leg.delta_target,
                        initial_strike=spx_price
                    )
                    if not option:
                        print(f"Could not find appropriate {leg.leg_type} for delta {leg.delta_target}")
                        return False
                    base_strike = option.contract.strike
                    
                else:  # For long legs
                    # Use the corresponding short leg's strike plus offset
                    base_strike = contracts[-1].strike + leg.strike_offset
                
                # Create contract
                contract = Contract()
                contract.symbol = "SPX"
                contract.secType = "OPT"
                contract.exchange = "CBOE"
                contract.currency = "USD"
                contract.lastTradeDateOrContractMonth = expiry
                contract.strike = base_strike
                contract.right = leg.leg_type
                contract.multiplier = "100"
                contracts.append(contract)
                
                # Create order
                order = Order()
                order.action = "BUY" if leg.position == 1 else "SELL"
                order.totalQuantity = abs(leg.quantity * trade_config.quantity)
                order.orderType = "MKT"
                order.transmit = False  # Only transmit last order
                orders.append(order)
            
            # Set last order to transmit
            if orders:
                orders[-1].transmit = True
            
            # Submit orders
            for i, (contract, order) in enumerate(zip(contracts, orders)):
                order_id = self.connection_manager.wrapper.next_order_id + i
                self.connection_manager.client.placeOrder(order_id, contract, order)
                print(f"Submitted {order.action} order for {contract.right} {contract.strike} {contract.lastTradeDateOrContractMonth}")
            
            # Set up monitoring for exit conditions
            if trade_config.exit_conditions:
                self.monitor_position_exits(trade_config)
            
            return True
            
        except Exception as e:
            print(f"Error executing trade: {e}")
            return False

    def handle_risk_event(self, event: str, details: Dict):
        """Handle risk events"""
        print(f"Risk Event: {event}")
        print(f"Details: {details}")
        
        # Exit position if needed
        if event in ["DELTA_BREACH", "LOSS_BREACH"]:
            current_position = self.get_current_position()
            if current_position:
                self.exit_position(current_position)
    
    def monitor_positions(self):
        """Monitor active positions for risk"""
        while self.running:
            try:
                position = self.get_current_position()
                if position:
                    risk_status = self.risk_monitor.check_position_risk(position)
                    if self.risk_monitor.should_exit_position(risk_status):
                        self.exit_position(position)
                time.sleep(1)  # Check every second
            except Exception as e:
                print(f"Error monitoring positions: {e}")
                time.sleep(5) 

    def exit_position(self, position) -> bool:
        """Exit an existing position"""
        try:
            print(f"Exiting position: {position.contract.strike} {position.contract.right} {position.contract.lastTradeDateOrContractMonth}")
            
            # Create exit order
            order = Order()
            order.action = "SELL" if position.position > 0 else "BUY"  # Opposite of current position
            order.totalQuantity = abs(position.position)
            order.orderType = "MKT"  # Market order for immediate exit
            order.transmit = True
            
            # Submit order
            if self.connection_manager.wrapper.next_order_id:
                self.connection_manager.client.placeOrder(
                    self.connection_manager.wrapper.next_order_id,
                    position.contract,
                    order
                )
                print(f"Exit order submitted: {self.connection_manager.wrapper.next_order_id}")
                return True
            else:
                print("No order ID available for exit")
                return False
            
        except Exception as e:
            print(f"Error exiting position: {e}")
            return False 

    def check_trade_time(self, trade_config: TradeConfig) -> bool:
        """Check if it's time to execute a specific trade"""
        now = datetime.now(pytz.timezone('US/Eastern'))
        current_time = now.time()
        current_day = now.strftime('%A')
        
        # Convert entry_time from string to time object
        entry_time = datetime.strptime(trade_config.entry_time, "%H:%M").time()
        
        # Check if current day is in entry_days and time matches
        return (current_day in trade_config.entry_days and 
                current_time.hour == entry_time.hour and 
                current_time.minute == entry_time.minute)

    def monitor_trades(self):
        """Monitor for trade entry opportunities"""
        while self.running:
            try:
                if not is_market_hours():
                    time.sleep(60)  # Sleep for 1 minute outside market hours
                    continue
                
                # Check each trade configuration
                for trade_name, config in self.trade_configs.items():
                    if not config.active:
                        continue
                        
                    if self.check_trade_time(config):
                        print(f"Executing trade: {trade_name}")
                        success = self.execute_trade(config)
                        if success:
                            print(f"Successfully executed {trade_name}")
                        else:
                            print(f"Failed to execute {trade_name}")
                            
                time.sleep(1)  # Check every second during market hours
                
            except Exception as e:
                print(f"Error in trade monitoring: {e}")
                time.sleep(5) 