import time
import threading
import queue
import logging
from datetime import datetime
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.execution import Execution
from ibapi.common import BarData
from ibapi.ticktype import TickTypeEnum
from ibapi.utils import iswrapper

# Import our own modules
from config.settings import (
    TWS_HOST, TWS_PORT, TWS_CLIENT_ID, TWS_MAX_RECONNECT_ATTEMPTS,
    TWS_RECONNECT_INTERVAL, MARKET_DATA_TYPE, DEBUG_MODE
)
from utils.logging_utils import setup_logger

# Set up logger
logger = setup_logger("tws_connector")

class IBAPIWrapper(EWrapper):
    """
    Wrapper class that receives callbacks from TWS
    """
    def __init__(self):
        super().__init__()
        # Initialize message queue for thread synchronization
        self.msg_queue = queue.Queue()
        
        # Initialize dictionaries to store market data
        self.tick_data = {}  # Stores latest tick data by reqId
        self.option_chains = {}  # Stores option chain data by reqId
        self.order_statuses = {}  # Stores order status info by orderId
        self.positions = {}  # Stores current positions
        self.account_values = {}  # Stores account information
        
        # Initialize callback dictionaries
        self.market_data_callbacks = {}  # Callbacks for market data updates
        self.order_callbacks = {}  # Callbacks for order status updates
        self.position_callbacks = []  # Callbacks for position updates
        self.error_callbacks = []  # Callbacks for error messages
        self.connection_callbacks = []  # Callbacks for connection status
        
        # Connection status
        self.connected = False
        self.connection_error = False
        
        # Next valid orderId
        self.next_order_id = None
    
    def nextValidId(self, orderId: int):
        """
        Callback from TWS with the next valid order ID
        
        Args:
            orderId: Next valid order ID
        """
        super().nextValidId(orderId)
        logger.debug(f"Next valid order ID: {orderId}")
        self.next_order_id = orderId
        self.connected = True
        self.connection_error = False
        
        # Notify connection callbacks
        for callback in self.connection_callbacks:
            callback(True)
    
    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        """
        Callback from TWS for error messages
        
        Args:
            reqId: Request ID
            errorCode: Error code
            errorString: Error message
            advancedOrderRejectJson: Additional error information
        """
        super().error(reqId, errorCode, errorString, advancedOrderRejectJson)
        
        # Log the error
        if errorCode < 2000:  # System or warning message
            logger.warning(f"TWS Error (reqId={reqId}): {errorCode} - {errorString}")
        else:  # API error
            logger.error(f"TWS Error (reqId={reqId}): {errorCode} - {errorString}")
        
        # Check for connection errors
        if errorCode in [1100, 1101, 1102, 1300, 2110]:
            self.connection_error = True
            self.connected = False
            
            # Notify connection callbacks
            for callback in self.connection_callbacks:
                callback(False)
        
        # Notify error callbacks
        for callback in self.error_callbacks:
            callback(reqId, errorCode, errorString)
    
    def connectionClosed(self):
        """Callback from TWS when the connection is closed"""
        super().connectionClosed()
        logger.warning("TWS connection closed")
        self.connected = False
        
        # Notify connection callbacks
        for callback in self.connection_callbacks:
            callback(False)
    
    def tickPrice(self, reqId: int, tickType: int, price: float, attrib):
        """
        Callback from TWS for price updates
        
        Args:
            reqId: Request ID
            tickType: Type of tick
            price: Price value
            attrib: Additional attributes
        """
        super().tickPrice(reqId, tickType, price, attrib)
        
        # Store the tick data
        if reqId not in self.tick_data:
            self.tick_data[reqId] = {}
        
        # Update the tick data dictionary
        self.tick_data[reqId][tickType] = price
        
        # Process market data callbacks
        if reqId in self.market_data_callbacks:
            for callback in self.market_data_callbacks.get(reqId, []):
                callback(reqId, tickType, price)
    
    def tickSize(self, reqId: int, tickType: int, size: int):
        """
        Callback from TWS for size updates
        
        Args:
            reqId: Request ID
            tickType: Type of tick
            size: Size value
        """
        super().tickSize(reqId, tickType, size)
        
        # Store the tick data
        if reqId not in self.tick_data:
            self.tick_data[reqId] = {}
        
        # Update the tick data dictionary
        self.tick_data[reqId][tickType] = size
        
        # Process market data callbacks
        if reqId in self.market_data_callbacks:
            for callback in self.market_data_callbacks.get(reqId, []):
                callback(reqId, tickType, size)
    
    def tickOptionComputation(self, reqId: int, tickType: int, impliedVol: float, delta: float, 
                             optPrice: float, pvDividend: float, gamma: float, vega: float, 
                             theta: float, undPrice: float):
        """
        Callback from TWS for option computation data
        
        Args:
            reqId: Request ID
            tickType: Type of tick
            impliedVol: Implied volatility
            delta: Option delta
            optPrice: Option price
            pvDividend: Present value of dividends
            gamma: Option gamma
            vega: Option vega
            theta: Option theta
            undPrice: Underlying price
        """
        super().tickOptionComputation(reqId, tickType, impliedVol, delta, optPrice, 
                                   pvDividend, gamma, vega, theta, undPrice)
        
        # Store the option data
        if reqId not in self.option_chains:
            self.option_chains[reqId] = {}
        
        # Update the option chain dictionary
        self.option_chains[reqId][tickType] = {
            "impliedVol": impliedVol,
            "delta": delta,
            "optPrice": optPrice,
            "gamma": gamma,
            "vega": vega,
            "theta": theta,
            "undPrice": undPrice
        }
        
        # Process market data callbacks
        if reqId in self.market_data_callbacks:
            for callback in self.market_data_callbacks.get(reqId, []):
                callback(reqId, tickType, {
                    "impliedVol": impliedVol,
                    "delta": delta,
                    "optPrice": optPrice,
                    "gamma": gamma,
                    "vega": vega,
                    "theta": theta,
                    "undPrice": undPrice
                })
    
    def orderStatus(self, orderId: int, status: str, filled: float, remaining: float, 
                   avgFillPrice: float, permId: int, parentId: int, lastFillPrice: float, 
                   clientId: int, whyHeld: str, mktCapPrice: float):
        """
        Callback from TWS for order status updates
        
        Args:
            orderId: Order ID
            status: Order status
            filled: Number of contracts filled
            remaining: Number of contracts remaining
            avgFillPrice: Average fill price
            permId: Permanent ID
            parentId: Parent order ID
            lastFillPrice: Last fill price
            clientId: Client ID
            whyHeld: Why the order is held
            mktCapPrice: Market cap price
        """
        super().orderStatus(orderId, status, filled, remaining, avgFillPrice, permId, 
                          parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        
        # Store order status
        self.order_statuses[orderId] = {
            "status": status,
            "filled": filled,
            "remaining": remaining,
            "avgFillPrice": avgFillPrice,
            "lastFillPrice": lastFillPrice,
            "whyHeld": whyHeld,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Log order status
        logger.info(f"Order {orderId} status: {status}, filled: {filled}/{filled+remaining} at {avgFillPrice}")
        
        # Process order callbacks
        if orderId in self.order_callbacks:
            for callback in self.order_callbacks.get(orderId, []):
                callback(orderId, status, filled, remaining, avgFillPrice, lastFillPrice, whyHeld)
    
    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        """
        Callback from TWS for position updates
        
        Args:
            account: Account number
            contract: Contract information
            position: Position size
            avgCost: Average cost
        """
        super().position(account, contract, position, avgCost)
        
        # Create a position key
        key = f"{contract.symbol}_{contract.secType}_{contract.right}_{contract.strike}_{contract.lastTradeDateOrContractMonth}"
        
        # Store position
        self.positions[key] = {
            "account": account,
            "contract": contract,
            "position": position,
            "avgCost": avgCost,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Log position
        logger.info(f"Position: {contract.symbol} {contract.secType} {position} @ {avgCost}")
        
        # Process position callbacks
        for callback in self.position_callbacks:
            callback(account, contract, position, avgCost)
    
    def register_market_data_callback(self, req_id, callback):
        """
        Register a callback for market data updates
        
        Args:
            req_id: Request ID
            callback: Callback function
        """
        if req_id not in self.market_data_callbacks:
            self.market_data_callbacks[req_id] = []
        self.market_data_callbacks[req_id].append(callback)
    
    def register_order_callback(self, order_id, callback):
        """
        Register a callback for order status updates
        
        Args:
            order_id: Order ID
            callback: Callback function
        """
        if order_id not in self.order_callbacks:
            self.order_callbacks[order_id] = []
        self.order_callbacks[order_id].append(callback)
    
    def register_position_callback(self, callback):
        """
        Register a callback for position updates
        
        Args:
            callback: Callback function
        """
        self.position_callbacks.append(callback)
    
    def register_error_callback(self, callback):
        """
        Register a callback for error messages
        
        Args:
            callback: Callback function
        """
        self.error_callbacks.append(callback)
    
    def register_connection_callback(self, callback):
        """
        Register a callback for connection status changes
        
        Args:
            callback: Callback function
        """
        self.connection_callbacks.append(callback)


class IBAPIClient(EClient):
    """
    Client class that communicates with TWS
    """
    def __init__(self, wrapper):
        super().__init__(wrapper)
        self.wrapper = wrapper


class IBAPIApp(IBAPIWrapper, IBAPIClient):
    """
    Application class that combines wrapper and client
    """
    def __init__(self):
        IBAPIWrapper.__init__(self)
        IBAPIClient.__init__(self, wrapper=self)
        
        # Initialize thread for message queue processing
        self.thread = None
        self.thread_running = False
        self.thread_stop_event = threading.Event()
    
    def start_queue_processing(self):
        """Start the message queue processing thread"""
        if self.thread_running:
            return
        
        self.thread_running = True
        self.thread_stop_event.clear()
        
        self.thread = threading.Thread(target=self._process_messages, daemon=True)
        self.thread.start()
    
    def stop_queue_processing(self):
        """Stop the message queue processing thread"""
        self.thread_running = False
        self.thread_stop_event.set()
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
    
    def _process_messages(self):
        """Process messages from the message queue"""
        while self.thread_running and not self.thread_stop_event.is_set():
            try:
                # Process messages with a timeout to allow for thread termination
                self.run(timeout=0.1)
            except Exception as e:
                logger.error(f"Error processing messages: {e}")
                time.sleep(0.1)  # Brief pause before retrying


class TWS:
    """
    Higher-level interface for TWS connectivity
    """
    def __init__(self, host=None, port=None, client_id=None):
        """
        Initialize the TWS connection manager
        
        Args:
            host: TWS host (default from settings)
            port: TWS port (default from settings)
            client_id: Client ID (default from settings)
        """
        self.host = host if host else TWS_HOST
        self.port = port if port else TWS_PORT
        self.client_id = client_id if client_id else TWS_CLIENT_ID
        
        # Initialize the API app
        self.app = IBAPIApp()
        
        # Initialize connection state
        self.connected = False
        self.connecting = False
        self.reconnect_attempts = 0
        self.reconnect_timer = None
    
    def connect(self):
        """
        Connect to TWS
        
        Returns:
            bool: True if connected successfully, False otherwise
        """
        if self.connected or self.connecting:
            return True
        
        self.connecting = True
        
        try:
            logger.info(f"Connecting to TWS at {self.host}:{self.port} (client_id={self.client_id})")
            
            # Connect to TWS
            self.app.connect(self.host, self.port, self.client_id)
            
            # Start message processing
            self.app.start_queue_processing()
            
            # Wait for nextValidId callback to confirm connection
            timeout = 10  # seconds
            start_time = time.time()
            
            while not self.app.connected and time.time() - start_time < timeout:
                time.sleep(0.1)
            
            if not self.app.connected:
                logger.error(f"Failed to connect to TWS after {timeout} seconds")
                self.app.stop_queue_processing()
                self.connecting = False
                return False
            
            # Set market data type
            logger.debug(f"Setting market data type to {MARKET_DATA_TYPE}")
            self.app.reqMarketDataType(MARKET_DATA_TYPE)
            
            # Request account updates
            logger.debug("Requesting account updates")
            self.app.reqAccountUpdates(True, "")
            
            # Request positions
            logger.debug("Requesting positions")
            self.app.reqPositions()
            
            self.connected = True
            self.connecting = False
            self.reconnect_attempts = 0
            
            logger.info("Connected to TWS successfully")
            return True
        
        except Exception as e:
            logger.error(f"Error connecting to TWS: {e}")
            self.app.stop_queue_processing()
            self.connecting = False
            return False
    
    def disconnect(self):
        """
        Disconnect from TWS
        
        Returns:
            bool: True if disconnected successfully, False otherwise
        """
        if not self.connected and not self.connecting:
            return True
        
        try:
            logger.info("Disconnecting from TWS")
            
            # Cancel the reconnect timer
            if self.reconnect_timer and self.reconnect_timer.is_alive():
                self.reconnect_timer.cancel()
            
            # Stop message processing
            self.app.stop_queue_processing()
            
            # Disconnect from TWS
            self.app.disconnect()
            
            self.connected = False
            self.connecting = False
            
            logger.info("Disconnected from TWS successfully")
            return True
        
        except Exception as e:
            logger.error(f"Error disconnecting from TWS: {e}")
            return False
    
    def reconnect(self):
        """
        Attempt to reconnect to TWS
        
        Returns:
            bool: True if reconnected successfully, False otherwise
        """
        if self.connected:
            return True
        
        # Increment reconnect attempts
        self.reconnect_attempts += 1
        
        if self.reconnect_attempts > TWS_MAX_RECONNECT_ATTEMPTS:
            logger.error(f"Exceeded maximum reconnect attempts ({TWS_MAX_RECONNECT_ATTEMPTS})")
            return False
        
        logger.info(f"Reconnecting to TWS (attempt {self.reconnect_attempts}/{TWS_MAX_RECONNECT_ATTEMPTS})")
        
        # First, try to disconnect if needed
        if self.connecting or self.app.isConnected():
            self.disconnect()
        
        # Then try to connect
        return self.connect()
    
    def schedule_reconnect(self):
        """Schedule a reconnection attempt"""
        if self.reconnect_timer and self.reconnect_timer.is_alive():
            return
        
        logger.info(f"Scheduling reconnect in {TWS_RECONNECT_INTERVAL} seconds")
        
        self.reconnect_timer = threading.Timer(TWS_RECONNECT_INTERVAL, self.reconnect)
        self.reconnect_timer.daemon = True
        self.reconnect_timer.start()
    
    def is_connected(self):
        """
        Check if connected to TWS
        
        Returns:
            bool: True if connected, False otherwise
        """
        return self.connected and self.app.isConnected()
    
    def get_next_order_id(self):
        """
        Get the next valid order ID
        
        Returns:
            int: Next valid order ID or None if not connected
        """
        if not self.is_connected():
            logger.error("Not connected to TWS")
            return None
        
        order_id = self.app.next_order_id
        if order_id is not None:
            self.app.next_order_id += 1
        
        return order_id
    
    def get_spx_price(self):
        """
        Get the current SPX price or last close price if market is closed
        
        Returns:
            float: SPX price
        """
        # Check if we're during market hours
        now = datetime.now()
        weekday = now.weekday()
        hour = now.hour
        minute = now.minute
        
        # Convert to Eastern time (crude approximation - in production use pytz)
        # Assuming server is in UTC, adjust for Eastern Time (UTC-4 or UTC-5)
        eastern_hour = (hour - 4) % 24  # Simple adjustment for Eastern Time
        
        # Check if market is open (M-F, 9:30 AM - 4:00 PM Eastern)
        market_open = (
            weekday < 5 and  # Monday to Friday
            (eastern_hour > 9 or (eastern_hour == 9 and minute >= 30)) and
            (eastern_hour < 16)
        )
        
        if market_open and self.is_connected():
            # Request real-time price
            logger.info("Market is open, requesting real-time SPX price")
            return self._request_real_time_price("SPX")
        else:
            # Get historical close
            logger.info("Market is closed, using last available SPX price")
            return self._get_historical_close("SPX")

    def _request_real_time_price(self, symbol):
        """
        Request real-time price for a symbol
        
        Args:
            symbol: Symbol to request price for
        
        Returns:
            float: Current price
        """
        # Create a contract for the symbol
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        
        # Create a queue for the response
        price_queue = queue.Queue()
        
        # Request market data
        req_id = self._get_next_request_id()
        
        # Define callback to process the response
        def price_callback(req_id, tick_type, price, *args):
            if tick_type == TickTypeEnum.LAST or tick_type == TickTypeEnum.CLOSE:
                price_queue.put(price)
        
        # Register the callback
        self.app.register_market_data_callback(req_id, price_callback)
        
        # Request market data
        self.app.reqMktData(req_id, contract, "", False, False, [])
        
        try:
            # Wait for the response (with timeout)
            price = price_queue.get(timeout=5.0)
            
            # Cancel the market data request
            self.app.cancelMktData(req_id)
            
            return price
        except queue.Empty:
            logger.warning(f"Timeout waiting for {symbol} price")
            # Cancel the market data request
            self.app.cancelMktData(req_id)
            # Fall back to historical data
            return self._get_historical_close(symbol)

    def _get_historical_close(self, symbol):
        """
        Get the last available closing price for a symbol
        
        Args:
            symbol: Symbol to get price for
        
        Returns:
            float: Last closing price
        """
        # Create a contract for the symbol
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        
        # Create a queue for the response
        bars_queue = queue.Queue()
        
        # Request historical data
        req_id = self._get_next_request_id()
        
        # Get current date/time
        end_datetime = datetime.now().strftime("%Y%m%d %H:%M:%S")
        
        # Define callback to process the response
        def hist_data_callback(req_id, bar):
            bars_queue.put(bar)
        
        # Register the callback
        self.app.register_historical_data_callback(req_id, hist_data_callback)
        
        # Request historical data (1 day of daily bars)
        self.app.reqHistoricalData(
            req_id, contract, end_datetime, "1 D", "1 day", 
            "TRADES", 1, 1, False, []
        )
        
        try:
            # Wait for the response (with timeout)
            bar = bars_queue.get(timeout=5.0)
            
            return float(bar.close)
        except queue.Empty:
            logger.warning(f"Timeout waiting for {symbol} historical data")
            # Fall back to a default value or last known price
            return 4500.0  # Default fallback
    
    def register_market_data_callback(self, req_id, callback):
        """Register a callback for market data updates"""
        self.app.register_market_data_callback(req_id, callback)
    
    def register_order_callback(self, order_id, callback):
        """Register a callback for order status updates"""
        self.app.register_order_callback(order_id, callback)
    
    def register_position_callback(self, callback):
        """Register a callback for position updates"""
        self.app.register_position_callback(callback)
    
    def register_error_callback(self, callback):
        """Register a callback for error messages"""
        self.app.register_error_callback(callback)
    
    def register_connection_callback(self, callback):
        """Register a callback for connection status changes"""
        self.app.register_connection_callback(callback)


# Usage example
if __name__ == "__main__":
    tws = TWS()
    
    # Connect to TWS
    if tws.connect():
        print("Connected to TWS")
        
        # Get SPX price
        spx_price = tws.get_spx_price()
        print(f"SPX price: {spx_price}")
        
        # Disconnect
        tws.disconnect()
        print("Disconnected from TWS")
    else:
        print("Failed to connect to TWS")
