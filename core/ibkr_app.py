import logging
from datetime import datetime
from typing import Dict, List, Optional

from ibapi.client import EClient
from ibapi.common import BarData, TickAttrib
from ibapi.contract import Contract, ContractDetails
from ibapi.execution import Execution
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.utils import decimalMaxString
from ibapi.wrapper import EWrapper

class IBKRApp(EWrapper, EClient):
    """
    Custom implementation of EWrapper and EClient to interact with IBKR API
    """
    
    def __init__(self):
        """Initialize the app with logger and data structures"""
        EClient.__init__(self, self)
        
        # Set up logging
        self.logger = logging.getLogger("ibkr_app")
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
        
        # Data structures for storing responses
        self.next_order_id = None
        self.contract_details = []
        self.contract_details_end_flag = False
        self.market_data = {}
        self.historical_data = {}
        self.historical_data_end_flag = False
        self.account_summary = {}
        self.positions = []
        self.account_ready = False
        self.current_orders = {}
        self.executions = []
        self.option_chains = {}
        self.tick_data = {}
        self.implied_vol = {}
        
        self.logger.info("IBKRApp initialized")
    
    # Connection and system methods
    def connectAck(self):
        """Called when connection is established"""
        self.logger.info("Connection to IBKR established")
    
    def connectionClosed(self):
        """Called when connection is closed"""
        self.logger.info("Connection to IBKR closed")
    
    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = ""):
        """Called when there is an error with the API"""
        if errorCode == 2104 or errorCode == 2106 or errorCode == 2158:  # Market data farm connection is OK
            return
        
        if errorCode == 202:  # Order cancelled
            self.logger.info(f"Order {reqId} cancelled: {errorString}")
            return
        
        if errorCode == 399:  # No data of type TV / OI, skipping
            return
        
        if reqId != -1:  # Log with specific request ID
            self.logger.error(f"Error {errorCode} for request {reqId}: {errorString}")
        else:  # General error
            self.logger.error(f"Error {errorCode}: {errorString}")
    
    def nextValidId(self, orderId: int):
        """Called when next valid order ID is received"""
        self.next_order_id = orderId
        self.logger.info(f"Next valid order ID: {orderId}")
    
    # Contract details methods
    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        """Called when contract details are received"""
        self.contract_details.append(contractDetails)
    
    def contractDetailsEnd(self, reqId: int):
        """Called when all contract details have been received"""
        self.logger.info(f"Received {len(self.contract_details)} contract details")
        self.contract_details_end_flag = True
    
    # Market data methods
    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: TickAttrib):
        """Called when price tick is received"""
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        
        if tickType == 1:  # Bid price
            self.market_data[reqId]['bid'] = price
        elif tickType == 2:  # Ask price
            self.market_data[reqId]['ask'] = price
        elif tickType == 4:  # Last price
            self.market_data[reqId]['last'] = price
        elif tickType == 9:  # Close price
            self.market_data[reqId]['close'] = price
        
        # Track all ticks for debugging
        if reqId not in self.tick_data:
            self.tick_data[reqId] = {}
        
        self.tick_data[reqId][f'tick_{tickType}'] = price
    
    def tickSize(self, reqId: int, tickType: int, size: int):
        """Called when size tick is received"""
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        
        if tickType == 0:  # Bid size
            self.market_data[reqId]['bid_size'] = size
        elif tickType == 3:  # Ask size
            self.market_data[reqId]['ask_size'] = size
        elif tickType == 5:  # Last size
            self.market_data[reqId]['last_size'] = size
        elif tickType == 8:  # Volume
            self.market_data[reqId]['volume'] = size
    
    def tickString(self, reqId: int, tickType: int, value: str):
        """Called when string tick is received"""
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        
        if tickType == 45:  # LastTimestamp
            self.market_data[reqId]['timestamp'] = value
    
    def tickGeneric(self, reqId: int, tickType: int, value: float):
        """Called when generic tick is received"""
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        
        # Store tick value for later reference
        self.market_data[reqId][f'generic_{tickType}'] = value
        
        # Handle implied volatility
        if tickType == 24:  # ImpliedVol
            self.market_data[reqId]['iv'] = value
    
    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        """
        Handle option computation ticks (Greeks)
        
        Args:
            reqId: Request ID
            tickType: Type of tick (10-13 for option computations)
            tickAttrib: Tick attributes
            impliedVol: Implied volatility
            delta: Delta
            optPrice: Option price
            pvDividend: PV Dividend
            gamma: Gamma
            vega: Vega
            theta: Theta
            undPrice: Underlying price
        """
        # Initialize market data entry if not exists
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        
        # IB API uses 1.7976931348623157E308 (DBL_MAX) to indicate unset values
        max_double = 1.7976931348623157e+308
        
        # Only process MODEL_OPTION_COMPUTATION (13)
        if tickType == 13 and delta is not None and delta != max_double:
            # Store delta as absolute value
            self.market_data[reqId]['delta'] = abs(delta)
            
            # Store other Greeks if they're valid
            if gamma != max_double:
                self.market_data[reqId]['gamma'] = gamma
            if vega != max_double:
                self.market_data[reqId]['vega'] = vega
            if theta != max_double:
                self.market_data[reqId]['theta'] = theta
            if impliedVol != max_double:
                self.market_data[reqId]['iv'] = impliedVol
            
            self.logger.debug(f"Received delta for reqId {reqId}: {abs(delta):.4f} (original: {delta:.4f})")
    
    # Historical data methods
    def historicalData(self, reqId: int, bar: BarData):
        """Called when historical data bar is received"""
        if reqId not in self.historical_data:
            self.historical_data[reqId] = []
        
        self.historical_data[reqId].append({
            'date': bar.date,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume,
            'wap': bar.wap,
            'count': bar.barCount
        })
    
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        """Called when all historical data has been received"""
        self.logger.info(f"Received {len(self.historical_data.get(reqId, []))} historical data bars")
        self.historical_data_end_flag = True
    
    # Account and position methods
    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str):
        """Called when account summary data is received"""
        if account not in self.account_summary:
            self.account_summary[account] = {}
        
        self.account_summary[account][tag] = {
            'value': value,
            'currency': currency
        }
    
    def accountSummaryEnd(self, reqId: int):
        """Called when all account summary data has been received"""
        self.logger.info(f"Received account summary for {len(self.account_summary)} accounts")
        self.account_ready = True
    
    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        """Called when position data is received"""
        self.positions.append({
            'account': account,
            'contract': contract,
            'position': position,
            'avgCost': avgCost
        })
    
    def positionEnd(self):
        """Called when all position data has been received"""
        self.logger.info(f"Received {len(self.positions)} positions")
    
    # Order methods
    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState: OrderState):
        """Called when open order data is received"""
        self.current_orders[orderId] = {
            'contract': contract,
            'order': order,
            'state': orderState
        }
    
    def openOrderEnd(self):
        """Called when all open order data has been received"""
        self.logger.info(f"Received {len(self.current_orders)} open orders")
    
    def orderStatus(self, orderId: int, status: str, filled: float, remaining: float, avgFillPrice: float,
                   permId: int, parentId: int, lastFillPrice: float, clientId: int, whyHeld: str, mktCapPrice: float):
        """Called when order status changes"""
        if orderId in self.current_orders:
            self.current_orders[orderId]['status'] = status
            self.current_orders[orderId]['filled'] = filled
            self.current_orders[orderId]['remaining'] = remaining
            self.current_orders[orderId]['avgFillPrice'] = avgFillPrice
        
        self.logger.info(f"Order {orderId} status: {status}, filled: {filled}, remaining: {remaining}")
    
    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        """Called when execution details are received"""
        self.executions.append({
            'reqId': reqId,
            'contract': contract,
            'execution': execution
        })
        
        self.logger.info(f"Received execution: {execution.orderId}, {execution.execId}, {execution.shares} shares at {execution.price}")
