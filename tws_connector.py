from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import BarData
from ibapi.order_state import OrderState
from ibapi.execution import Execution
from ibapi.order import Order
from ibapi.contract import ComboLeg
from threading import Thread
import time
import queue
from datetime import datetime, timedelta
import pytz
from dataclasses import dataclass
from typing import Dict, Optional, List

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
        self.data_queue.put((
            'order_status',
            orderId,
            status,
            filled,
            remaining,
            avgFillPrice
        ))
    
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
        # Store in queue for processing
        self.data_queue.put(('price', reqId, tickType, price))
        
        # For SPX index (main underlying)
        if reqId == 1 and tickType == 4:  # Last price
            self.spx_price = price
    
    def tickOption(self, reqId, tickType, impliedVol, delta, gamma, vega, theta, undPrice):
        """Called when option tick data is received"""
        print(f"\nOption tick received:")
        print(f"reqId: {reqId}")
        print(f"tickType: {tickType}")
        print(f"impliedVol: {impliedVol}")
        print(f"delta: {delta}")
        print(f"gamma: {gamma}")
        print(f"vega: {vega}")
        print(f"theta: {theta}")
        print(f"undPrice: {undPrice}")
        
        # Store in queue for processing
        self.data_queue.put(('option_tick', reqId, tickType, impliedVol, delta, gamma, vega, theta))
        
        # Only process meaningful updates
        if delta != -2 or impliedVol > 0:
            # Find the corresponding option
            for opt in self.positions.values():
                if opt.contract.conId == reqId:
                    if delta != -2:
                        print(f"Option Greeks - Strike: {opt.contract.strike}, Delta: {delta:.3f}")
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

    def tickOptionComputation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        """Called when option computation data is received"""
        # Store in queue for processing without debug output
        self.data_queue.put(('option_computation', reqId, tickType, impliedVol, delta, gamma, vega, theta, optPrice))

    def position(self, account, contract, pos, avg_cost):
        if contract.symbol == "SPX" and contract.secType == "OPT":
            key = f"{contract.symbol}_{contract.right}_{contract.strike}_{contract.lastTradeDateOrContractMonth}"
            self.positions[key] = OptionPosition(contract, pos, avg_cost)
            # Request market data for this option
            self.data_queue.put(('request_option_data', contract))
        self.data_queue.put(('position', contract, pos, avg_cost))

    def historicalData(self, reqId: int, bar: BarData):
        self.data_queue.put(('historical', reqId, bar))

    def contractDetails(self, reqId: int, contractDetails):
        """Called by TWS when contract details are received"""
        self.data_queue.put(('contract_details', reqId, contractDetails))
        
    def contractDetailsEnd(self, reqId: int):
        """Called by TWS when all contract details have been received"""
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
    spx_price = None  # Class attribute
    
    def __init__(self, host='127.0.0.1', port=7496, client_id=1):
        # Initialize parent classes
        IBWrapper.__init__(self)
        TWS.__init__(self, wrapper=self)
        
        # Initialize parent class attributes
        self.data_queue = queue.Queue()
        self.positions = {}
        self.next_order_id = None
        
        # Initialize own attributes
        self.host = host
        self.port = port
        self.client_id = client_id
        self.connected = False
        self.et_timezone = pytz.timezone('US/Eastern')
        self._next_req_id = 1
        
        # Order tracking
        self.order_status: Dict[int, str] = {}
        self.executions: Dict[int, List[Execution]] = {}
        
    def get_next_req_id(self):
        self._next_req_id += 1
        return self._next_req_id
        
    def connect(self):
        if not self.connected:
            super().connect(self.host, self.port, self.client_id)
            self.start()
            
            # Wait for nextValidId
            timeout = time.time() + 5  # 5 second timeout
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
        """Create an SPX Weekly option contract"""
        contract = Contract()
        
        # Basic fields
        contract.symbol = "SPX"
        contract.secType = "OPT"
        contract.currency = "USD"
        contract.exchange = "CBOE"
        contract.tradingClass = "SPXW"
        
        # Option details
        contract.right = right
        contract.strike = strike
        contract.lastTradeDateOrContractMonth = expiry
        contract.multiplier = "100"
        
        # Format local symbol exactly as TWS expects
        # Example for Jan 27 2025 6100 Put: "spxw 250127P06100000"
        yy = expiry[2:4]
        mm = expiry[4:6]
        dd = expiry[6:8]
        strike_int = int(strike)
        strike_padded = f"{strike_int:05d}000"  # 5 digits + "000"
        contract.localSymbol = f"spxw {yy}{mm}{dd}{right}{strike_padded}"  # Single space after 'spxw'
        
        print(f"\nCreated contract:")
        print(f"Local Symbol: {contract.localSymbol}")
        print(f"Symbol: {contract.symbol}")
        print(f"Trading Class: {contract.tradingClass}")
        print(f"Strike: {contract.strike}")
        print(f"Expiry: {contract.lastTradeDateOrContractMonth}")
        print(f"Right: {contract.right}")
        print(f"Exchange: {contract.exchange}")
        
        return contract

    def is_market_hours(self):
        """Check if we're in SPX market hours (9:30 AM - 4:15 PM ET, Mon-Fri)"""
        now = datetime.now(self.et_timezone)
        if now.weekday() > 4:  # Weekend
            return False
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=15, second=0, microsecond=0)
        return market_open <= now <= market_close
        
    def request_spx_data(self, req_id=1):
        """Request SPX price data - real-time during market hours, last close otherwise"""
        contract = self.get_spx_contract()
        
        if self.is_market_hours():
            # During market hours - request real-time data
            self.reqMktData(req_id, contract, "", False, False, [])
        else:
            # Outside market hours - get last closing price
            end_time = ""  # Empty string means "now"
            self.reqHistoricalData(
                reqId=req_id,
                contract=contract,
                endDateTime=end_time,
                durationStr="1 D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=1,
                formatDate=1,
                keepUpToDate=False,
                chartOptions=[]
            )
    
    def request_option_data(self, contract: Contract):
        """Request market data for an option position"""
        req_id = self.get_next_req_id()
        print(f"\nRequesting market data for option:")
        print(f"Strike: {contract.strike}")
        print(f"Right: {contract.right}")
        print(f"Expiry: {contract.lastTradeDateOrContractMonth}")
        print(f"Local Symbol: {contract.localSymbol}")
        print(f"reqId: {req_id}")
        
        # Request specific tick types:
        # 13: Last (Historical Volatility)
        # 14: Model Option Computation
        # 24: IV (Implied Volatility)
        # 31: Last Timestamp
        self.reqMktData(req_id, contract, "13,14,24,31", False, False, [])
        return req_id
        
    def request_positions(self):
        """Request current positions"""
        self.positions.clear()  # Clear existing positions before requesting updates
        self.reqPositions()
        
    def get_total_delta(self) -> float:
        """Calculate total delta exposure across all positions"""
        return sum(pos.delta * pos.position if pos.delta is not None else 0 
                  for pos in self.positions.values())
        
    def get_max_risk(self) -> float:
        """Calculate maximum risk across all positions"""
        total_risk = 0
        for pos in self.positions.values():
            if pos.position < 0:  # Short positions
                if pos.contract.right == "C":  # Short calls
                    total_risk = float('inf')  # Unlimited risk
                else:  # Short puts
                    total_risk += pos.contract.strike * 100 * abs(pos.position)
        return total_risk 

    def submit_order(self, contract: Contract, order: Order, order_id: int):
        """Wrapper for placeOrder with additional validation"""
        # Validate contract
        if not contract.symbol:
            raise ValueError("Contract symbol is missing")
        if not contract.secType:
            raise ValueError("Contract secType is missing")
        if not contract.exchange:
            raise ValueError("Contract exchange is missing")
        if contract.secType == "OPT":
            if not contract.right:
                raise ValueError("Option right is missing")
            if not contract.strike:
                raise ValueError("Option strike is missing")
            if not contract.lastTradeDateOrContractMonth:
                raise ValueError("Option expiry is missing")
            if not contract.multiplier:
                raise ValueError("Option multiplier is missing")
            
        # Log order details
        print(f"\nSubmitting Order:")
        print(f"Order ID: {order_id}")
        print(f"Contract: {contract.symbol} {contract.tradingClass} {contract.exchange}")
        print(f"Details: {contract.right} {contract.strike} {contract.lastTradeDateOrContractMonth}")
        print(f"Order Type: {order.orderType}")
        print(f"Action: {order.action}")
        print(f"Quantity: {order.totalQuantity}")
        if hasattr(order, 'lmtPrice') and order.lmtPrice:
            print(f"Limit Price: {order.lmtPrice}")
            
        # Submit the order
        self.placeOrder(order_id, contract, order) 

    def request_option_chain(self, expiry: str, right: str, min_strike: float, max_strike: float, target_delta: float = 0.15) -> List[OptionPosition]:
        """Request option chain data for SPX options within a strike range"""
        print("\nDEBUG: Entering request_option_chain")
        
        # Create base contract - keep it simple
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "OPT"
        contract.exchange = "CBOE"
        contract.strike = min_strike
        contract.right = right
        contract.lastTradeDateOrContractMonth = expiry
        
        print("\nDEBUG: Contract created:")
        print(f"Symbol: {contract.symbol}")
        print(f"Strike: {contract.strike}")
        print(f"Expiry: {contract.lastTradeDateOrContractMonth}")
        print(f"Right: {contract.right}")
        print(f"Exchange: {contract.exchange}")
        
        # Request contract details
        req_id = self.get_next_req_id()
        print(f"\nDEBUG: Requesting contract details with reqId: {req_id}")
        self.reqContractDetails(req_id, contract)
        
        # Wait for contract details
        contract_found = False
        qualified_contract = None
        start_time = time.time()
        
        while time.time() - start_time < 5:
            try:
                msg = self.data_queue.get(timeout=0.1)
                print(f"\nDEBUG: Received message: {msg[0]}")
                
                if msg[0] == 'contract_details':
                    print("DEBUG: Got contract details")
                    contract_found = True
                    qualified_contract = msg[2].contract
                    break
                elif msg[0] == 'error':
                    print(f"DEBUG: Error received: {msg}")
                    
            except queue.Empty:
                continue
        
        if not contract_found:
            print("DEBUG: No contract details found")
            return []
            
        # Request market data
        req_id = self.get_next_req_id()
        print(f"\nDEBUG: Requesting market data with reqId: {req_id}")
        self.reqMktData(req_id, qualified_contract, "", False, False, [])
        
        # Wait for Greeks data
        got_data = False
        start_time = time.time()
        current_delta = None
        option_data = None
        
        while time.time() - start_time < 5:
            try:
                msg = self.data_queue.get(timeout=0.1)
                print(f"\nDEBUG: Received market data message: {msg[0]}")
                
                if msg[0] == 'option_computation':
                    _, msg_req_id, tick_type, impl_vol, msg_delta, gamma, vega, theta, opt_price = msg
                    print(f"DEBUG: Option computation - delta: {msg_delta}, IV: {impl_vol}")
                    
                    if msg_req_id == req_id and msg_delta != -2 and msg_delta != 0:
                        got_data = True
                        current_delta = msg_delta
                        
                        option_data = OptionPosition(
                            contract=qualified_contract,
                            position=0,
                            avg_cost=0,
                            delta=current_delta,
                            implied_vol=impl_vol if impl_vol > 0 else None,
                            gamma=gamma if gamma != -2 else None,
                            vega=vega if vega != -2 else None,
                            theta=theta if theta != -2 else None
                        )
                        break
                        
            except queue.Empty:
                continue
        
        # Cancel market data request
        print("\nDEBUG: Canceling market data request")
        self.cancelMktData(req_id)
        
        if got_data:
            print(f"\nDEBUG: Returning option with delta: {current_delta}")
            return [option_data]
        else:
            print("\nDEBUG: No market data received")
            return []

    def request_spx_historical_data(self):
        """Request historical data for SPX to get the previous closing price"""
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        
        # Request 1 day of historical data, ending at the current time
        # This will give us the previous closing price
        end_datetime = ""  # Empty string means "now"
        self.reqHistoricalData(
            reqId=1,
            contract=contract,
            endDateTime=end_datetime,
            durationStr="1 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=1,
            formatDate=1,
            keepUpToDate=False,
            chartOptions=[]
        )

    def historicalData(self, reqId: int, bar):
        """Callback for historical data"""
        if reqId == 1:  # SPX historical data
            self.spx_price = bar.close
            self.cancelHistoricalData(reqId)
        self.data_queue.put(('historical', reqId, bar))

    def contractDetails(self, reqId: int, contractDetails):
        """Called by TWS when contract details are received"""
        self.data_queue.put(('contract_details', reqId, contractDetails))
        
    def contractDetailsEnd(self, reqId: int):
        """Called by TWS when all contract details have been received"""
        self.data_queue.put(('contract_details_end', reqId))

    def get_option_price(self, contract: Contract) -> float:
        """Get the mid price (bid+ask)/2 for an option"""
        req_id = self.get_next_req_id()
        self.reqMktData(req_id, contract, "100,101", False, False, [])  # Request bid/ask
        
        start_time = time.time()
        bid = None
        ask = None
        
        while time.time() - start_time < 2:  # 2 second timeout
            try:
                msg = self.data_queue.get(timeout=0.1)
                if msg[0] == 'price':
                    _, msg_req_id, tick_type, price = msg
                    if msg_req_id == req_id:
                        if tick_type == 1:  # Bid
                            bid = price
                        elif tick_type == 2:  # Ask
                            ask = price
                        
                        if bid is not None and ask is not None:
                            break
                            
            except queue.Empty:
                continue
                
        self.cancelMktData(req_id)
        
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        else:
            return 0.0  # Return 0 if we couldn't get both bid and ask 

    def create_iron_condor_order(self, 
                               put_wing_contract: Contract,
                               put_contract: Contract, 
                               call_contract: Contract,
                               call_wing_contract: Contract,
                               quantity: int = 1,
                               total_credit: float = 0.0) -> Order:
        """Create a BAG order for an iron condor spread"""
        
        # Round limit price to nearest 0.05 and make it negative (for credit orders)
        limit_price = -round(total_credit * 20) / 20  # Make price negative for credit orders
        
        # Create the combo legs
        combo_legs = []
        
        # Long put wing (BUY = positive ratio)
        leg1 = ComboLeg()
        leg1.conId = put_wing_contract.conId
        leg1.ratio = 1
        leg1.action = "BUY"
        leg1.exchange = "SMART"
        
        # Short put (SELL = negative ratio)
        leg2 = ComboLeg()
        leg2.conId = put_contract.conId
        leg2.ratio = 1
        leg2.action = "SELL"
        leg2.exchange = "SMART"
        
        # Short call (SELL = negative ratio)
        leg3 = ComboLeg()
        leg3.conId = call_contract.conId
        leg3.ratio = 1
        leg3.action = "SELL"
        leg3.exchange = "SMART"
        
        # Long call wing (BUY = positive ratio)
        leg4 = ComboLeg()
        leg4.conId = call_wing_contract.conId
        leg4.ratio = 1
        leg4.action = "BUY"
        leg4.exchange = "SMART"
        
        combo_legs.extend([leg1, leg2, leg3, leg4])
        
        # Create the BAG contract
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "BAG"
        contract.currency = "USD"
        contract.exchange = "SMART"
        contract.comboLegs = combo_legs
        
        # Create the order
        order = Order()
        order.orderType = "LMT"
        order.totalQuantity = quantity
        order.lmtPrice = limit_price  # Using negative price for credit
        order.action = "BUY"
        order.tif = "DAY"
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        
        return contract, order
        
    def submit_iron_condor(self,
                          put_wing_contract: Contract,
                          put_contract: Contract,
                          call_contract: Contract,
                          call_wing_contract: Contract,
                          quantity: int = 1,
                          total_credit: float = 0.0) -> int:
        """Submit an iron condor order"""
        
        # Get next valid order ID
        order_id = self.next_order_id
        self.next_order_id += 1
        
        # Create the BAG contract and order
        contract, order = self.create_iron_condor_order(
            put_wing_contract=put_wing_contract,
            put_contract=put_contract,
            call_contract=call_contract,
            call_wing_contract=call_wing_contract,
            quantity=quantity,
            total_credit=total_credit
        )
        
        # Submit the order
        print(f"\nSubmitting Iron Condor order:")
        print(f"Order ID: {order_id}")
        print(f"Quantity: {quantity}")
        print(f"Limit Price: {order.lmtPrice:.2f}")
        print("\nLegs:")
        print(f"1. BUY  {put_wing_contract.strike} Put")
        print(f"2. SELL {put_contract.strike} Put")
        print(f"3. SELL {call_contract.strike} Call")
        print(f"4. BUY  {call_wing_contract.strike} Call")
        
        self.placeOrder(order_id, contract, order)
        return order_id 