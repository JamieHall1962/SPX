"""
CORE TWS CONNECTIVITY - DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION
Contains essential TWS connection and market data handling
"""

import sys
from pathlib import Path

# Add project root to Python path
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.append(root_dir)

from threading import Lock, Thread, Event
import time
import traceback
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from utils.date_utils import get_next_futures_month
from dataclasses import dataclass
import logging

# Disable all TWS API logging
logging.getLogger('RISK').disabled = True
logging.getLogger('ibapi.wrapper').disabled = True
logging.getLogger('ibapi.client').disabled = True
logging.getLogger('ibapi.decoder').disabled = True
logging.getLogger('ibapi').disabled = True

@dataclass
class OptionPosition:
    """Represents an option position"""
    contract: Contract
    position: int
    market_price: float = 0.0
    market_value: float = 0.0
    average_cost: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

class IBWrapper(EWrapper):
    """TWS API Wrapper - Core Functionality"""
    
    def __init__(self):
        """Initialize wrapper"""
        super().__init__()
        self.spx_price = None
        self.es_price = None
        self._market_callbacks = []
        self._callback_lock = Lock()
        self._option_chain_data = {}
        self._option_chain_complete = {}
        self._option_chain_event = Event()
        self._next_req_id = 2000
        self.client = None
        print("IBWrapper initialized")

    def set_client(self, client):
        """Set the client instance"""
        self.client = client

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib):
        """Direct price update handling"""
        if tickType in [1, 2, 4, 6, 9, 14]:  # Bid, Ask, Last, High, Low, Open
            if reqId == 1:
                self.spx_price = price
                self._notify_callbacks({"symbol": "SPX", "price": price})
            elif reqId == 2:
                self.es_price = price
                self._notify_callbacks({"symbol": "ES", "price": price})

    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = ""):
        """Handle TWS errors"""
        print(f"TWS Error - ID: {reqId}, Code: {errorCode}, Message: {errorString}")

    def _notify_callbacks(self, market_data):
        """Notify callbacks with market data"""
        with self._callback_lock:
            for callback in self._market_callbacks:
                try:
                    callback(market_data)
                except Exception as e:
                    print(f"Callback error: {e}")
                    traceback.print_exc()

class IBClient(EClient):
    """TWS API Client - Core Functionality"""
    
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)

class ConnectionManager:
    """TWS Connection Manager - Core Functionality"""
    
    def __init__(self):
        """Initialize connection manager"""
        print("Initializing ConnectionManager...")
        self.wrapper = IBWrapper()
        self.client = IBClient(self.wrapper)
        self.wrapper.client = self.client
        self._running = False
        self._status_callbacks = []
        self._callback_lock = Lock()
        self.host = "127.0.0.1"
        self.port = 7496
        self.client_id = 1
        
        # Disable TWS API debug logging
        logging.getLogger('RISK').setLevel(logging.ERROR)

    def connect(self) -> bool:
        """Connect to TWS with dedicated thread"""
        try:
            print("Connecting to TWS...")
            
            # Force disconnect if already connected
            if self.client.isConnected():
                print("Already connected - disconnecting first")
                self.client.disconnect()
                time.sleep(1)
            
            # Connect
            self.client.connect(self.host, self.port, self.client_id)
            
            # Start client thread
            thread = Thread(target=self.client.run)
            thread.daemon = True  # Make thread daemon so it exits when main program exits
            thread.start()
            
            # Wait for connection
            time.sleep(2)
            
            if self.client.isConnected():
                print("Connected to TWS")
                self._running = True
                self.request_market_data()
                return True
            else:
                print("Failed to connect")
                return False
                
        except Exception as e:
            print(f"Connection error: {e}")
            traceback.print_exc()
            return False

    def disconnect(self):
        """Disconnect from TWS"""
        if self.client.isConnected():
            self.client.disconnect()
            self._running = False

    def is_connected(self) -> bool:
        """Check if TWS is connected"""
        return self.client.isConnected()

    def request_market_data(self):
        """Simplified market data request"""
        if not self.client.isConnected():
            return
            
        try:
            # SPX Index
            spx = Contract()
            spx.symbol = "SPX"
            spx.secType = "IND"
            spx.exchange = "CBOE"
            spx.currency = "USD"
            
            # ES Future
            es = Contract()
            es.symbol = "ES"
            es.secType = "FUT"
            es.exchange = "CME"
            es.currency = "USD"
            es.lastTradeDateOrContractMonth = get_next_futures_month()
            
            print("Requesting market data...")
            self.client.reqMktData(1, spx, "", False, False, [])
            self.client.reqMktData(2, es, "", False, False, [])
            
        except Exception as e:
            print(f"Market data request error: {e}")
            traceback.print_exc()

    def get_status(self) -> dict:
        """Simple status check"""
        return {
            "connected": self.client.isConnected(),
            "spx_price": self.wrapper.spx_price,
            "es_price": self.wrapper.es_price
        }

    def get_tws(self):
        """Get TWS wrapper"""
        if not self.client.isConnected():
            self.connect()
        return self.wrapper if self.client.isConnected() else None

    def add_market_callback(self, callback) -> int:
        """Add a market data callback"""
        with self._callback_lock:
            self.wrapper._market_callbacks.append(callback)
            return len(self.wrapper._market_callbacks) - 1

    def remove_market_callback(self, callback_id: int):
        """Remove a market data callback"""
        with self._callback_lock:
            if 0 <= callback_id < len(self.wrapper._market_callbacks):
                self.wrapper._market_callbacks.pop(callback_id)

    def add_status_callback(self, callback) -> int:
        """Add a connection status callback"""
        with self._callback_lock:
            self._status_callbacks.append(callback)
            return len(self._status_callbacks) - 1

    def remove_status_callback(self, callback_id: int):
        """Remove a status callback"""
        with self._callback_lock:
            if 0 <= callback_id < len(self._status_callbacks):
                self._status_callbacks.pop(callback_id)