# core/trade_engine.py
import logging
import threading
import time
from datetime import datetime, timedelta
import math
from queue import Queue

from config.settings import TRADING_ACTIVE, SANDBOX_MODE
from config.trade_config import TradeType, MarketCondition
from utils.logging_utils import setup_logger
from utils.notifications import notify_error, notify_trade_executed

# Set up logger
logger = setup_logger("trade_engine")

class TradeEngine:
    """
    Core trade engine for executing and managing trades
    """
    def __init__(self, tws_connector):
        """
        Initialize the trade engine
        
        Args:
            tws_connector: TWS connector instance
        """
        self.tws = tws_connector
        self.running = False
        self.trading_thread = None
        self.active_strategies = []
        self.executed_trades = {}
        self.last_run_times = {}
        
        # For tracking positions
        self.positions = {}
        self.order_statuses = {}
        
        # Operation queues
        self.command_queue = Queue()
        
        # Register callbacks
        self.tws.register_position_callback(self._on_position_update)
        self.tws.register_connection_callback(self._on_connection_status)
        self.tws.register_error_callback(self._on_error)
    
    def start(self):
        """Start the trade engine"""
        if self.running:
            logger.warning("Trade engine already running")
            return
        
        logger.info("Starting trade engine")
        
        self.running = True
        
        # Start trading thread
        self.trading_thread = threading.Thread(target=self._trading_loop)
        self.trading_thread.daemon = True
        self.trading_thread.start()
        
        logger.info("Trade engine started")
    
    def stop(self):
        """Stop the trade engine"""
        if not self.running:
            logger.warning("Trade engine already stopped")
            return
        
        logger.info("Stopping trade engine")
        
        self.running = False
        
        # Wait for the trading thread to exit
        if self.trading_thread and self.trading_thread.is_alive():
            self.trading_thread.join(timeout=5)
        
        logger.info("Trade engine stopped")
    
    def add_strategy(self, strategy):
        """
        Add a trading strategy
        
        Args:
            strategy: Strategy configuration
        """
        self.active_strategies.append(strategy)
        self.last_run_times[strategy.name] = None
        logger.info(f"Added strategy: {strategy.name}")
    
    def remove_strategy(self, strategy_name):
        """
        Remove a trading strategy by name
        
        Args:
            strategy_name: Name of the strategy to remove
        """
        for i, strategy in enumerate(self.active_strategies):
            if strategy.name == strategy_name:
                self.active_strategies.pop(i)
                if strategy_name in self.last_run_times:
                    del self.last_run_times[strategy_name]
                logger.info(f"Removed strategy: {strategy_name}")
                return True
        
        logger.warning(f"Strategy not found: {strategy_name}")
        return False
    
    def execute_order(self, order_id, contract, order, strategy_name):
        """
        Execute an order
        
        Args:
            order_id: Order ID
            contract: Contract to trade
            order: Order to execute
            strategy_name: Name of the strategy executing the order
            
        Returns:
            bool: True if the order was placed, False otherwise
        """
        if not TRADING_ACTIVE:
            logger.warning("Trading is disabled - order not placed")
            return False
        
        if SANDBOX_MODE:
            logger.info(f"SANDBOX MODE: Order would be placed: {order.action} {order.totalQuantity} {contract.symbol} @ {order.orderType}")
            return True
        
        try:
            logger.info(f"Placing order: {order.action} {order.totalQuantity} {contract.symbol} @ {order.orderType}")
            
            # Place the order
            self.tws.app.placeOrder(order_id, contract, order)
            
            # Register callback for order status
            self.tws.register_order_callback(order_id, self._on_order_status)
            
            # Record the order
            self.order_statuses[order_id] = {
                "contract": contract,
                "order": order,
                "strategy": strategy_name,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "Submitted"
            }
            
            logger.info(f"Order placed: ID={order_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            notify_error(f"Failed to place order: {e}")
            return False
    
    def cancel_order(self, order_id):
        """
        Cancel an order
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            bool: True if the order was cancelled, False otherwise
        """
        if not order_id in self.order_statuses:
            logger.warning(f"Order not found: {order_id}")
            return False
        
        if SANDBOX_MODE:
            logger.info(f"SANDBOX MODE: Order would be cancelled: {order_id}")
            return True
        
        try:
            logger.info(f"Cancelling order: {order_id}")
            
            # Cancel the order
            self.tws.app.cancelOrder(order_id)
            
            # Update the order status
            self.order_statuses[order_id]["status"] = "Cancelled"
            
            logger.info(f"Order cancelled: {order_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            notify_error(f"Failed to cancel order: {e}")
            return False
    
    def _trading_loop(self):
        """Main trading loop"""
        while self.running:
            # Process any pending commands
            self._process_commands()
            
            # Check if TWS is connected
            if not self.tws.is_connected():
                logger.warning("Not connected to TWS - reconnecting")
                self.tws.reconnect()
                time.sleep(5)
                continue
            
            # Check for strategies to run
            for strategy in self.active_strategies:
                # Skip inactive strategies
                if not strategy.active:
                    continue
                
                # Check if it's time to run this strategy
                if self._should_run_strategy(strategy):
                    self._run_strategy(strategy)
            
            # Check for position management
            self._manage_positions()
            
            # Sleep before next iteration
            time.sleep(1)
    
    def _process_commands(self):
        """Process commands from the command queue"""
        while not self.command_queue.empty():
            try:
                cmd, args = self.command_queue.get_nowait()
                
                if cmd == "add_strategy":
                    self.add_strategy(args["strategy"])
                
                elif cmd == "remove_strategy":
                    self.remove_strategy(args["strategy_name"])
                
                elif cmd == "cancel_order":
                    self.cancel_order(args["order_id"])
                
                self.command_queue.task_done()
            
            except Exception as e:
                logger.error(f"Error processing command: {e}")
    
    def _should_run_strategy(self, strategy):
        """
        Check if a strategy should be run
        
        Args:
            strategy: Strategy configuration
            
        Returns:
            bool: True if the strategy should be run, False otherwise
        """
        now = datetime.now()
        today_weekday = now.weekday()  # 0 = Monday, 6 = Sunday
        
        # Check if today is a valid trading day for this strategy
        if strategy.entry_days and today_weekday not in strategy.entry_days:
            return False
        
        # Check if we've already run this strategy today
        last_run = self.last_run_times.get(strategy.name)
        if last_run and last_run.date() == now.date():
            return False
        
        # Check if it's the right time to run this strategy
        if strategy.entry_time:
            strategy_time = strategy.entry_time
            now_time = now.time()
            
            # Time window: strategy time - 5 minutes to strategy time + 5 minutes
            time_window_start = datetime.combine(now.date(), strategy_time) - timedelta(minutes=5)
            time_window_end = datetime.combine(now.date(), strategy_time) + timedelta(minutes=5)
            
            return time_window_start <= now <= time_window_end
        
        return True
    
    def _run_strategy(self, strategy):
        """
        Run a trading strategy
        
        Args:
            strategy: Strategy configuration
        """
        logger.info(f"Running strategy: {strategy.name}")
        
        try:
            # Record the run time
            self.last_run_times[strategy.name] = datetime.now()
            
            # Run the appropriate strategy based on type
            if strategy.trade_type == TradeType.IRON_CONDOR:
                self._run_iron_condor(strategy)
            
            elif strategy.trade_type == TradeType.DOUBLE_CALENDAR:
                self._run_double_calendar(strategy)
            
            elif strategy.trade_type == TradeType.PUT_BUTTERFLY:
                self._run_put_butterfly(strategy)
            
            else:
                logger.warning(f"Unsupported strategy type: {strategy.trade_type}")
        
        except Exception as e:
            logger.error(f"Error running strategy {strategy.name}: {e}")
            notify_error(f"Failed to run strategy {strategy.name}: {e}")
    
    def _run_iron_condor(self, strategy):
        """
        Run an iron condor strategy
        
        Args:
            strategy: Iron condor strategy configuration
        """
        # This is a placeholder - actual implementation will use the StrikeSelector
        logger.info(f"Running iron condor strategy: {strategy.name}")
        
        # Get current SPX price
        spx_price = self.tws.get_spx_price()
        
        if not spx_price:
            logger.error("Failed to get SPX price")
            return
        
        logger.info(f"Current SPX price: {spx_price}")
        
        # Example implementation (to be completed)
        # 1. Select strikes
        # 2. Create contracts
        # 3. Create orders
        # 4. Execute orders
    
    def _run_double_calendar(self, strategy):
        """
        Run a double calendar strategy
        
        Args:
            strategy: Double calendar strategy configuration
        """
        # This is a placeholder - actual implementation will use the StrikeSelector
        logger.info(f"Running double calendar strategy: {strategy.name}")
        
        # Implementation to be completed
    
    def _run_put_butterfly(self, strategy):
        """
        Run a put butterfly strategy
        
        Args:
            strategy: Put butterfly strategy configuration
        """
        # This is a placeholder - actual implementation will use the StrikeSelector
        logger.info(f"Running put butterfly strategy: {strategy.name}")
        
        # Implementation to be completed
    
    def _manage_positions(self):
        """Manage open positions"""
        # This is a placeholder - actual implementation will manage open positions
        # Implementation to be completed
    
    def _on_position_update(self, account, contract, position, avg_cost):
        """
        Callback for position updates
        
        Args:
            account: Account ID
            contract: Contract
            position: Position size
            avg_cost: Average cost
        """
        symbol = contract.symbol
        
        # Store the position
        if symbol not in self.positions:
            self.positions[symbol] = {}
        
        self.positions[symbol][contract.right + str(contract.strike)] = {
            "contract": contract,
            "position": position,
            "avg_cost": avg_cost,
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        logger.info(f"Position update: {symbol} {contract.right}{contract.strike}: {position} @ {avg_cost}")
    
    def _on_connection_status(self, connected):
        """
        Callback for connection status updates
        
        Args:
            connected: True if connected, False otherwise
        """
        if connected:
            logger.info("Connected to TWS")
        else:
            logger.warning("Disconnected from TWS")
    
    def _on_error(self, req_id, error_code, error_msg):
        """
        Callback for error messages
        
        Args:
            req_id: Request ID
            error_code: Error code
            error_msg: Error message
        """
        if error_code < 2000:  # System or warning message
            logger.warning(f"TWS Error {error_code}: {error_msg}")
        else:  # API error
            logger.error(f"TWS Error {error_code}: {error_msg}")
            
            # Notify about critical errors
            if error_code >= 2000:
                notify_error(f"TWS Error {error_code}: {error_msg}")
    
    def _on_order_status(self, order_id, status, filled, remaining, avg_fill_price, *args):
        """
        Callback for order status updates
        
        Args:
            order_id: Order ID
            status: Order status
            filled: Number of contracts filled
            remaining: Number of contracts remaining
            avg_fill_price: Average fill price
            *args: Additional arguments
        """
        logger.info(f"Order {order_id} status: {status}, filled: {filled}/{filled+remaining} at {avg_fill_price}")
        
        if status == "Filled":
            # Order is filled, record the trade
            trade_info = {
                "order_id": order_id,
                "status": status,
                "filled": filled,
                "avg_fill_price": avg_fill_price,
                "filled_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            logger.info(f"Order {order_id} filled: {trade_info}")
            
            # Notify about the executed trade
            notify_trade_executed(trade_info)
