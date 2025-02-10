"""Handles all TWS connection and market data"""
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ComboLeg
from ibapi.order import Order
from ibapi.common import BarData
from ibapi.order_state import OrderState
from ibapi.execution import Execution
from threading import Lock, Thread
import time
from typing import Optional, List, Dict, Callable, Any
import queue
import pytz
from datetime import datetime, timedelta
from dataclasses import dataclass
import threading
import calendar
import logging
import traceback

@dataclass
class OptionPosition:
    contract: Contract
    position: float
    avg_cost: float
    market_price: Optional[float] = None
    implied_vol: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None

@dataclass
class MarketData:
    """Market data update"""
    symbol: str
    price: float
    time: str

@dataclass
class OrderStatus:
    orderId: str
    status: str    # Filled, Submitted, Cancelled, etc.
    filled: float  # Number of contracts filled
    remaining: float
    avgFillPrice: float
    lastFillPrice: float
    whyHeld: str  # Margin, risk limits, etc.

@dataclass
class Position:
    symbol: str
    position: int  # Number of contracts
    avgCost: float
    pnl: float

@dataclass
class AccountUpdate:
    key: str       # NetLiquidation, AvailableFunds, etc.
    value: float
    currency: str

class CallbackManager:
    def __init__(self):
        self._market_callbacks: List[Callable[[MarketData], None]] = []
        self._connection_callbacks: List[Callable[[bool], None]] = []
        self._order_callbacks: List[Callable[[OrderStatus], None]] = []
        self._position_callbacks: List[Callable[[Position], None]] = []
        self._account_callbacks: List[Callable[[AccountUpdate], None]] = []
        self._error_callbacks: List[Callable[[int, str], None]] = []
        self._callback_lock = Lock()
        self._last_market_update: Dict[str, float] = {}  # Timestamp of last update
        self.MIN_UPDATE_INTERVAL = 0.1  # Minimum seconds between updates

    def _safe_callback(self, callback: Callable, *args):
        """Execute callback with error handling"""
        try:
            callback(*args)
        except Exception as e:
            logging.error(f"Error in callback: {e}")

    def add_market_callback(self, callback: Callable[[MarketData], None]) -> int:
        """Add market data callback"""
        with self._callback_lock:
            self._market_callbacks.append(callback)
            return len(self._market_callbacks) - 1

    def remove_market_callback(self, callback_id: int):
        """Remove market callback"""
        with self._callback_lock:
            if 0 <= callback_id < len(self._market_callbacks):
                self._market_callbacks[callback_id] = None

    def notify_market_update(self, market_data: MarketData):
        """Notify market data update"""
        with self._callback_lock:
            for callback in self._market_callbacks:
                if callback:
                    self._safe_callback(callback, market_data)

    def add_order_callback(self, callback: Callable[[OrderStatus], None]) -> int:
        """Track order submissions, fills, cancellations"""
        with self._callback_lock:
            self._order_callbacks.append(callback)
            return len(self._order_callbacks) - 1

    def add_position_callback(self, callback: Callable[[Position], None]) -> int:
        """Track position changes and P&L updates"""
        with self._callback_lock:
            self._position_callbacks.append(callback)
            return len(self._position_callbacks) - 1

    def add_account_callback(self, callback: Callable[[AccountUpdate], None]) -> int:
        """Track account value changes (margin, equity, etc.)"""
        with self._callback_lock:
            self._account_callbacks.append(callback)
            return len(self._account_callbacks) - 1

    def notify_order_update(self, order_status: OrderStatus):
        """Notify on order status changes"""
        with self._callback_lock:
            for callback in self._order_callbacks:
                if callback:
                    self._safe_callback(callback, order_status)

    def notify_position_update(self, position: Position):
        """Notify on position changes"""
        with self._callback_lock:
            for callback in self._position_callbacks:
                if callback:
                    self._safe_callback(callback, position)

    def notify_account_update(self, account_update: AccountUpdate):
        """Notify on account value changes"""
        with self._callback_lock:
            for callback in self._account_callbacks:
                if callback:
                    self._safe_callback(callback, account_update)

    def add_connection_callback(self, callback: Callable[[bool], None]) -> int:
        """Add connection status callback"""
        with self._callback_lock:
            self._connection_callbacks.append(callback)
            return len(self._connection_callbacks) - 1

    def remove_connection_callback(self, callback_id: int):
        """Remove connection callback"""
        with self._callback_lock:
            if 0 <= callback_id < len(self._connection_callbacks):
                self._connection_callbacks[callback_id] = None

    def notify_connection_change(self, connected: bool):
        """Notify connection status change"""
        with self._callback_lock:
            for callback in self._connection_callbacks:
                if callback:
                    self._safe_callback(callback, connected)

class IBWrapper(EWrapper):
    def __init__(self):
        print("Initializing IBWrapper...")
        super().__init__()
        self.spx_price = None
        self.es_price = None
        self.next_order_id = None
        self._status_callbacks = []
        print("IBWrapper initialized")
        
    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = ""):
        """Handle TWS errors"""
        print(f"TWS Error - ID: {reqId}, Code: {errorCode}, Message: {errorString}")
        # Don't call super().error() as it's causing the argument mismatch

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib):
        """Handle price updates"""
        if tickType in [1, 2, 4, 6, 9, 14]:  # Bid, Ask, Last, High, Low, Open
            if reqId == 1:  # SPX
                self.spx_price = price
                self._notify_callbacks()
            elif reqId == 2:  # ES
                self.es_price = price
                self._notify_callbacks()
                
    def tickString(self, reqId: int, tickType: int, value: str):
        """Handle string tick types"""
        pass
        
    def tickGeneric(self, reqId: int, tickType: int, value: float):
        """Handle generic tick types"""
        pass
        
    def tickSize(self, reqId: int, tickType: int, size: int):
        """Handle size tick types"""
        pass
    
    def tickOption(self, reqId, tickType, impliedVol, delta, gamma, vega, theta, undPrice):
        """Called when option tick data is received"""
        self.data_queue.put(('option_tick', reqId, tickType, impliedVol, delta, gamma, vega, theta))
        
        if delta != -2 or impliedVol > 0:
            for opt in self.positions.values():
                if opt.contract.conId == reqId:
                    if delta != -2:
                        opt.delta = delta
                    if impliedVol > 0:
                        opt.implied_vol = impliedVol
                    if gamma != -2:
                        opt.gamma = gamma
                    if vega != -2:
                        opt.vega = vega
                    if theta != -2:
                        opt.theta = theta
                    break

    def tickOptionComputation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, 
                            delta: float, optPrice: float, pvDividend: float, gamma: float, 
                            vega: float, theta: float, undPrice: float):
        self.data_queue.put(('option_computation', reqId, tickType, impliedVol, delta, gamma, vega, theta, optPrice))

    def position(self, account, contract, pos, avg_cost):
        if contract.symbol == "SPX" and contract.secType == "OPT":
            key = f"{contract.symbol}_{contract.right}_{contract.strike}_{contract.lastTradeDateOrContractMonth}"
            self.positions[key] = OptionPosition(contract, pos, avg_cost)
            self.data_queue.put(('request_option_data', contract))
        self.data_queue.put(('position', contract, pos, avg_cost))

    def historicalData(self, reqId: int, bar: BarData):
        self.data_queue.put(('historical', reqId, bar))

    def contractDetails(self, reqId: int, contractDetails):
        self.data_queue.put(('contract_details', reqId, contractDetails))
        
    def contractDetailsEnd(self, reqId: int):
        self.data_queue.put(('contract_details_end', reqId))

    def nextValidId(self, orderId: int):
        """Called when connection is established"""
        print(f"Connected to TWS (Next Order ID: {orderId})")
        self.next_order_id = orderId

    def _notify_callbacks(self):
        """Notify all callbacks of status update"""
        for callback in self._status_callbacks:
            try:
                status = {
                    "connected": True,
                    "spx_price": self.spx_price,
                    "es_price": self.es_price
                }
                callback(status)
            except Exception as e:
                print(f"Error in status callback: {e}")

    def orderStatus(self, orderId: int, status: str, filled: float,
                   remaining: float, avgFillPrice: float, permId: int,
                   parentId: int, lastFillPrice: float, clientId: int,
                   whyHeld: str, mktCapPrice: float):
        """Handle order status updates"""
        print(f"Order {orderId} status: {status}")
        print(f"Filled: {filled}, Remaining: {remaining}, Avg Fill Price: {avgFillPrice}")

class IBClient(EClient):
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)
        self.wrapper = wrapper
        self._thread = None
        
    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = Thread(target=self.run)
            self._thread.start()
            
    def stop(self):
        self.done = True
        if self._thread is not None:
            self._thread.join()

class TWSConnector(IBWrapper, IBClient):
    def __init__(self, host='127.0.0.1', port=7496, client_id=1):
        IBWrapper.__init__(self)
        IBClient.__init__(self, wrapper=self)
        
        self.data_queue = queue.Queue()
        self.positions = {}
        self.next_order_id = None
        
        self.host = host
        self.port = port
        self.client_id = client_id
        self.connected = False
        self.et_timezone = pytz.timezone('US/Eastern')
        self._next_req_id = 1
        
        self.order_status: Dict[int, str] = {}
        self.executions: Dict[int, List[Execution]] = {}
        
    def get_next_req_id(self):
        self._next_req_id += 1
        return self._next_req_id
        
    def connect(self) -> bool:
        """Connect to TWS"""
        try:
            print("Attempting to connect to TWS...")
            self.connect("127.0.0.1", 7496, 1)  # Changed client ID to 1
            
            # Wait for connection
            max_wait = 10
            while max_wait > 0 and not self.isConnected():
                print(f"Waiting for connection... ({max_wait}s remaining)")
                time.sleep(1)
                max_wait -= 1
                
            if self.isConnected():
                print("Connected to TWS successfully")
                print("Requesting market data...")
                self.request_market_data()
                return True
            else:
                print("Failed to connect to TWS")
                return False
                
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from TWS"""
        if self.connected:
            print("Disconnecting from TWS...")
            self.stop()
            self.connected = False

    def get_spx_contract(self):
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        return contract

    def get_spx_option_contract(self, right: str, strike: float, expiry: str):
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "OPT"
        contract.currency = "USD"
        contract.exchange = "CBOE"
        contract.tradingClass = "SPXW"
        contract.right = right
        contract.strike = strike
        contract.lastTradeDateOrContractMonth = expiry
        contract.multiplier = "100"
        return contract

    def get_option_price(self, contract: Contract) -> float:
        req_id = self.get_next_req_id()
        self.reqMktData(req_id, contract, "100,101", False, False, [])
        
        start_time = time.time()
        bid = None
        ask = None
        
        while time.time() - start_time < 2:
            try:
                msg = self.data_queue.get(timeout=0.1)
                if msg[0] == 'price':
                    _, msg_req_id, tick_type, price = msg
                    if msg_req_id == req_id:
                        if tick_type == 1:
                            bid = price
                        elif tick_type == 2:
                            ask = price
                        if bid is not None and ask is not None:
                            break
            except queue.Empty:
                continue
                
        self.cancelMktData(req_id)
        
        if bid is not None and ask is not None:
            mid_price = round(((bid + ask) / 2) * 20) / 20
            return mid_price
        return 0.0

    def get_front_month_es(self) -> str:
        """Get the front month ES contract in YYYYMM format"""
        now = datetime.now()
        year = now.year
        month = now.month
        
        # ES futures use quarterly contracts (Mar, Jun, Sep, Dec)
        # Map current month to next quarterly contract
        if month <= 3:
            contract_month = 3  # March
        elif month <= 6:
            contract_month = 6  # June
        elif month <= 9:
            contract_month = 9  # September
        else:
            contract_month = 12  # December
        
        # If we're past the current quarter's expiration,
        # move to next quarter
        if month == contract_month and now.day > 15:  # After 3rd Friday (approx)
            if contract_month == 12:
                contract_month = 3
                year += 1
            else:
                contract_month += 3
        
        return f"{year}{contract_month:02d}"

    def get_next_futures_month(self) -> str:
        """Get the next ES futures contract month"""
        now = datetime.now()
        month = now.month
        year = now.year
        
        # ES futures cycle: H(Mar), M(Jun), U(Sep), Z(Dec)
        cycle = {
            3: 'H',  # March
            6: 'M',  # June
            9: 'U',  # September
            12: 'Z'  # December
        }
        
        # Find next expiration
        for exp_month in sorted(cycle.keys()):
            if month < exp_month:
                return f"{year}{exp_month:02d}"
            
        # If we're past December, use March of next year
        return f"{year + 1}03"

    def request_market_data(self):
        """Request market data for SPX and ES"""
        print("Setting up market data requests...")
        try:
            # SPX contract
            spx = Contract()
            spx.symbol = "SPX"
            spx.secType = "IND"
            spx.exchange = "CBOE"
            spx.currency = "USD"
            
            # ES contract
            es = Contract()
            es.symbol = "ES"
            es.secType = "FUT"
            es.exchange = "CME"
            es.currency = "USD"
            next_month = self.get_next_futures_month()
            es.lastTradeDateOrContractMonth = next_month
            
            # Request real-time market data
            print("Requesting market data with generic ticks...")
            # 233 = RT Volume (Time & Sales), 165 = Misc Stats
            generic_tick_list = "233,165"
            
            print("Requesting SPX data...")
            self.reqMktData(1, spx, generic_tick_list, False, False, [])
            
            print(f"Requesting ES data for contract: {next_month}")
            self.reqMktData(2, es, generic_tick_list, False, False, [])
            
        except Exception as e:
            print(f"Error requesting market data: {e}")
            traceback.print_exc()

    def maintain_connection(self):
        """Monitor and maintain TWS connection"""
        while True:
            try:
                if not self.isConnected():
                    print("Connection lost, attempting to reconnect...")
                    self.disconnect()
                    time.sleep(1)
                    self.connect("127.0.0.1", 7496, 0)
                    if self.isConnected():
                        print("Reconnected to TWS")
                        self.connected = True
                        self.request_market_data()  # Re-request market data after reconnect
                time.sleep(10)  # Check every 10 seconds
            except Exception as e:
                print(f"Error in connection maintenance: {e}")
                time.sleep(10)  # Wait before retry

    def create_es_contract(self) -> Contract:
        """Create ES futures contract with complete specification"""
        contract = Contract()
        contract.symbol = "ES"
        contract.secType = "FUT"
        contract.exchange = "CME"
        contract.currency = "USD"
        contract.multiplier = "50"  # ES contract multiplier
        contract.tradingClass = "ES"
        contract.lastTradeDateOrContractMonth = self.get_next_futures_month()
        return contract

class ConnectionManager:
    """Single source of truth for TWS connection and market data"""
    def __init__(self):
        print("Initializing ConnectionManager...")
        self.wrapper = IBWrapper()
        self.client = IBClient(self.wrapper)
        self._next_req_id = 1000
        self._status_callbacks = []
        self._market_callbacks = []
        self._callback_lock = Lock()
        self._running = False
        self._reconnect_thread = None
        print("ConnectionManager initialized")

    def start(self):
        """Start connection manager with reconnection"""
        self._running = True
        self._reconnect_thread = Thread(target=self._maintain_connection)
        self._reconnect_thread.daemon = True
        self._reconnect_thread.start()

    def stop(self):
        """Stop connection manager"""
        self._running = False
        if self._reconnect_thread:
            self._reconnect_thread.join(timeout=5)
        self.disconnect()

    def _maintain_connection(self):
        """Maintain connection and reconnect if needed"""
        while self._running:
            if not self.client.isConnected():
                print("Connection lost - attempting to reconnect...")
                if self.connect():
                    print("Reconnected successfully")
                else:
                    print("Reconnection failed, will retry in 30 seconds")
                    time.sleep(30)
            time.sleep(5)  # Check connection every 5 seconds

    def get_next_futures_month(self) -> str:
        """Get the next ES futures contract month"""
        now = datetime.now()
        month = now.month
        year = now.year
        
        # ES futures cycle: H(Mar), M(Jun), U(Sep), Z(Dec)
        cycle = {
            3: 'H',  # March
            6: 'M',  # June
            9: 'U',  # September
            12: 'Z'  # December
        }
        
        # Find next expiration
        for exp_month in sorted(cycle.keys()):
            if month < exp_month:
                return f"{year}{exp_month:02d}"
                
        # If we're past December, use March of next year
        return f"{year + 1}03"

    def request_market_data(self):
        """Request market data for SPX and ES"""
        print("Setting up market data requests...")
        try:
            # SPX contract
            spx = Contract()
            spx.symbol = "SPX"
            spx.secType = "IND"
            spx.exchange = "CBOE"
            spx.currency = "USD"
            
            # ES contract
            es = Contract()
            es.symbol = "ES"
            es.secType = "FUT"
            es.exchange = "CME"
            es.currency = "USD"
            next_month = self.get_next_futures_month()
            es.lastTradeDateOrContractMonth = next_month
            
            # Request real-time market data
            print("Requesting market data with generic ticks...")
            # 233 = RT Volume (Time & Sales), 165 = Misc Stats
            generic_tick_list = "233,165"
            
            print("Requesting SPX data...")
            self.client.reqMktData(1, spx, generic_tick_list, False, False, [])
            
            print(f"Requesting ES data for contract: {next_month}")
            self.client.reqMktData(2, es, generic_tick_list, False, False, [])
            
        except Exception as e:
            print(f"Error requesting market data: {e}")
            traceback.print_exc()

    def connect(self) -> bool:
        """Connect to TWS"""
        try:
            print("Attempting to connect to TWS...")
            self.client.connect("127.0.0.1", 7496, 1)
            
            # Start the client thread
            thread = Thread(target=self.client.run)
            thread.daemon = True
            thread.start()
            
            # Wait for connection
            max_wait = 10
            while max_wait > 0 and not self.client.isConnected():
                print(f"Waiting for connection... ({max_wait}s remaining)")
                time.sleep(1)
                max_wait -= 1
                
            if self.client.isConnected():
                print("Connected to TWS successfully")
                self.request_market_data()
                return True
            else:
                print("Failed to connect to TWS")
                return False
                
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from TWS"""
        if self.client.isConnected():
            self.client.disconnect()

    def add_status_callback(self, callback):
        """Add callback for status updates"""
        with self._callback_lock:
            self._status_callbacks.append(callback)
            # Add callback to wrapper as well
            self.wrapper._status_callbacks.append(callback)
            status = self.get_status()
            callback(status)
            return len(self._status_callbacks) - 1

    def add_market_callback(self, callback):
        """Add callback for market data updates"""
        with self._callback_lock:
            self._market_callbacks.append(callback)
            return len(self._market_callbacks) - 1

    def get_status(self) -> Dict[str, Any]:
        """Get current status"""
        return {
            "connected": self.client.isConnected(),
            "spx_price": self.wrapper.spx_price,
            "es_price": self.wrapper.es_price
        }

    def create_order(self, action: str, quantity: int, order_type: str = "MKT") -> Order:
        """Create an IB order"""
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = order_type
        return order
        
    def place_order(self, contract: Contract, order: Order) -> int:
        """Place an order and return the order id"""
        if not self.client.isConnected():
            print("Error: Not connected to TWS")
            return -1
            
        order_id = self._next_req_id
        self._next_req_id += 1
        
        try:
            print(f"Placing order {order_id}: {order.action} {order.totalQuantity} {contract.symbol}")
            self.client.placeOrder(order_id, contract, order)
            return order_id
        except Exception as e:
            print(f"Error placing order: {e}")
            return -1

    def remove_market_callback(self, callback_id: int):
        """Remove a market data callback"""
        with self._callback_lock:
            if 0 <= callback_id < len(self._market_callbacks):
                self._market_callbacks.pop(callback_id)

    def remove_status_callback(self, callback_id: int):
        """Remove a status callback"""
        with self._callback_lock:
            if 0 <= callback_id < len(self._status_callbacks):
                self._status_callbacks.pop(callback_id)