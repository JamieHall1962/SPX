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
from typing import Optional, List, Dict
import queue
import pytz
from datetime import datetime, timedelta
from dataclasses import dataclass

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

class IBWrapper(EWrapper):
    def __init__(self):
        super().__init__()
        self.data_queue = queue.Queue()
        self.positions: Dict[str, OptionPosition] = {}
        self.next_order_id = None
        
    def error(self, reqId, errorCode, errorString):
        if errorCode != 2104:  # Exclude market data farm connection message
            print(f'Error {errorCode}: {errorString}')
            self.data_queue.put(('error', reqId, errorCode, errorString))
    
    def nextValidId(self, orderId: int):
        """Called by TWS with the next valid order ID"""
        self.next_order_id = orderId
        self.data_queue.put(('next_order_id', orderId))
    
    def orderStatus(
        self, 
        orderId: int, 
        status: str, 
        filled: float,
        remaining: float, 
        avgFillPrice: float,
        permId: int, 
        parentId: int, 
        lastFillPrice: float, 
        clientId: int,
        whyHeld: str, 
        mktCapPrice: float
    ):
        """Called when the status of an order changes"""
        self.order_status[orderId] = status
        self.data_queue.put((
            'order_status',
            orderId,
            status,
            filled,
            remaining,
            avgFillPrice
        ))
        print(f"\nOrder {orderId} status update: {status}")
        if status == "Filled":
            print(f"Filled at price: {avgFillPrice}")
    
    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        """Called when an order is executed"""
        self.data_queue.put((
            'execution',
            reqId,
            contract,
            execution
        ))
    
    def tickPrice(self, reqId, tickType, price, attrib):
        """Called when price tick data is received"""
        self.data_queue.put(('price', reqId, tickType, price))
        
        if reqId == 1 and tickType == 4:  # Last price for SPX
            self.spx_price = price
            if hasattr(self, 'put_exit_price') and hasattr(self, 'call_exit_price'):
                if price <= self.put_exit_price:
                    print(f"\n⚠️ SPX price {price} has breached put exit level {self.put_exit_price}")
                    if hasattr(self, 'put_exit_order') and hasattr(self, 'short_put_contract'):
                        order_id = self.next_order_id
                        self.next_order_id += 1
                        print("\nSubmitting market order to close short put")
                        self.placeOrder(order_id, self.short_put_contract, self.put_exit_order)
                        del self.put_exit_price
                        del self.put_exit_order
                        del self.short_put_contract
                        
                elif price >= self.call_exit_price:
                    print(f"\n⚠️ SPX price {price} has breached call exit level {self.call_exit_price}")
                    if hasattr(self, 'call_exit_order') and hasattr(self, 'short_call_contract'):
                        order_id = self.next_order_id
                        self.next_order_id += 1
                        print("\nSubmitting market order to close short call")
                        self.placeOrder(order_id, self.short_call_contract, self.call_exit_order)
                        del self.call_exit_price
                        del self.call_exit_order
                        del self.short_call_contract
                        
        elif reqId == 2 and tickType == 4:  # Last price for ES
            self.es_price = price
    
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

class TWS(EClient):
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

class TWSConnector(IBWrapper, TWS):
    spx_price = None
    es_price = None
    
    def __init__(self, host='127.0.0.1', port=7496, client_id=1):
        IBWrapper.__init__(self)
        TWS.__init__(self, wrapper=self)
        
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
        
    def connect(self):
        if not self.connected:
            super().connect(self.host, self.port, self.client_id)
            self.start()
            
            timeout = time.time() + 5
            while self.next_order_id is None and time.time() < timeout:
                time.sleep(0.1)
            
            if self.next_order_id is None:
                raise ConnectionError("Failed to receive next valid order ID from TWS")
                
            self.connected = True
            
    def disconnect(self):
        if self.connected:
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

class ConnectionManager:
    def __init__(self, client_id: int = 0, max_retries: int = 3, retry_delay: int = 5):
        self.client_id = client_id
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.tws = None
        self.connected = False
        self.connection_lock = Lock()
        self.last_heartbeat = time.time()
        self.heartbeat_timeout = 10
        
        self.spx_price: Optional[float] = None
        self.es_price: Optional[float] = None
        
        self._start_heartbeat_thread()
    
    def connect(self) -> bool:
        with self.connection_lock:
            if self.connected:
                return True
            
            for attempt in range(self.max_retries):
                try:
                    print(f"Connection attempt {attempt + 1}/{self.max_retries}")
                    self.tws = TWSConnector(client_id=self.client_id)
                    self.tws.connect()
                    
                    timeout = time.time() + 5
                    while time.time() < timeout:
                        if self.tws.isConnected():
                            self.connected = True
                            self._subscribe_market_data()
                            return True
                        time.sleep(0.1)
                    
                    self._cleanup_connection()
                    
                except Exception as e:
                    print(f"Connection attempt failed: {str(e)}")
                    self._cleanup_connection()
                
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
            
            return False
    
    def _cleanup_connection(self):
        try:
            if self.tws:
                self.tws.disconnect()
                self.tws = None
            self.connected = False
            self.spx_price = None
            self.es_price = None
        except Exception as e:
            print(f"Error in cleanup: {str(e)}")
    
    def _start_heartbeat_thread(self):
        def heartbeat_monitor():
            while True:
                if self.connected:
                    if time.time() - self.last_heartbeat > self.heartbeat_timeout:
                        print("Heartbeat timeout - attempting reconnection")
                        self._handle_disconnection()
                time.sleep(1)
        
        self.heartbeat_thread = Thread(target=heartbeat_monitor, daemon=True)
        self.heartbeat_thread.start()
    
    def _handle_disconnection(self):
        with self.connection_lock:
            print("Handling disconnection...")
            self._cleanup_connection()
            self.connect()
    
    def _subscribe_market_data(self):
        if not self.connected or not self.tws:
            return
        
        try:
            spx_contract = self.tws.get_spx_contract()
            self.tws.reqMktData(1, spx_contract, "", False, False, [])
            
            es_contract = self._get_active_es_contract()
            self.tws.reqMktData(2, es_contract, "", False, False, [])
            
        except Exception as e:
            print(f"Error subscribing to market data: {str(e)}")
    
    def _get_active_es_contract(self):
        contract = Contract()
        contract.symbol = "ES"
        contract.secType = "FUT"
        contract.exchange = "CME"
        contract.currency = "USD"
        
        now = datetime.now()
        month = now.month
        year = now.year
        
        if month < 3:
            expiry_month = "03"
        elif month < 6:
            expiry_month = "06"
        elif month < 9:
            expiry_month = "09"
        elif month < 12:
            expiry_month = "12"
        else:
            expiry_month = "03"
            year += 1
            
        contract.lastTradeDateOrContractMonth = f"{year}{expiry_month}"
        return contract
    
    def is_connected(self) -> bool:
        return self.connected and self.tws and self.tws.isConnected()
    
    def update_heartbeat(self):
        self.last_heartbeat = time.time()
    
    def get_spx_price(self) -> Optional[float]:
        if self.tws:
            return self.tws.spx_price
        return None
    
    def get_es_price(self) -> Optional[float]:
        if self.tws:
            return self.tws.es_price
        return None
    
    def get_tws(self) -> Optional[TWSConnector]:
        return self.tws