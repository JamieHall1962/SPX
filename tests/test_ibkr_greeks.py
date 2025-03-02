from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import threading
import time
import logging
import datetime

class TestIBKRDelta(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        
        # Set up logging
        self.logger = logging.getLogger("test_ibkr_delta")
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
        
        self.option_data = {}
        self.data = []
        self.next_valid_id = None
        self.contract_details_end = False
        self.all_callbacks = []
        
    def nextValidId(self, orderId):
        self.next_valid_id = orderId
        self.logger.info(f"Connected to IBKR with ID: {orderId}")
        
    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        self.logger.error(f"Error {errorCode}: {errorString}")
    
    # Override every possible callback to track what's being called    
    def __getattr__(self, name):
        # Log all method calls to see what's happening
        if name.startswith('__'):
            return super().__getattr__(name)
            
        def method_logger(*args, **kwargs):
            self.all_callbacks.append(name)
            self.logger.debug(f"Callback: {name} with args: {args}")
        
        return method_logger
        
    def tickPrice(self, reqId, tickType, price, attrib):
        """Handle price ticks"""
        self.logger.debug(f"tickPrice: reqId={reqId}, tickType={tickType}, price={price}")
        
        if reqId not in self.option_data:
            self.option_data[reqId] = {}
            
        # Bid = 1, Ask = 2
        if tickType == 1:  # Bid
            self.option_data[reqId]['bid'] = price
        elif tickType == 2:  # Ask
            self.option_data[reqId]['ask'] = price
    
    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        """Handle option computations with correct signature"""
        self.logger.info(f"OPTION COMPUTATION: reqId={reqId}, tickType={tickType}, delta={delta}, tickAttrib={tickAttrib}")
        
        if delta is not None and delta != float('inf'):
            if reqId not in self.option_data:
                self.option_data[reqId] = {}
                
            # Find the contract info
            contract_info = next((opt for opt in self.data if opt['contract'].conId == reqId), None)
            if contract_info:
                # Store delta as absolute value
                self.option_data[reqId].update({
                    'delta': abs(delta),
                    'strike': contract_info['strike'],
                    'right': contract_info['contract'].right,
                    'impl_vol': impliedVol,
                    'gamma': gamma,
                    'vega': vega,
                    'theta': theta
                })
                
                # Log the delta
                self.logger.info(f"SUCCESS! Got delta for {contract_info['contract'].right} {contract_info['strike']}: {abs(delta):.4f}")
                
    def contractDetails(self, reqId, contractDetails):
        """Handle contract details"""
        contract = contractDetails.contract
        self.data.append({
            'contract': contract,
            'strike': contract.strike,
            'right': contract.right
        })
        self.logger.debug(f"Contract: {contract.right} {contract.strike}, conId={contract.conId}")
        
    def contractDetailsEnd(self, reqId):
        """Handle end of contract details"""
        self.contract_details_end = True
        self.logger.info(f"Received {len(self.data)} option contracts")

def main():
    app = TestIBKRDelta()
    
    # Connect to IBKR TWS/Gateway
    app.connect("127.0.0.1", 7496, 0)
    
    # Start API message processing thread
    api_thread = threading.Thread(target=app.run)
    api_thread.start()
    
    # Wait for connection
    start_time = time.time()
    while app.next_valid_id is None and time.time() - start_time < 30:
        time.sleep(0.1)
        
    if app.next_valid_id is None:
        app.logger.error("Failed to connect to IBKR")
        return
    
    # Create a contract for the underlying
    underlying = Contract()
    underlying.symbol = "SPX"
    underlying.secType = "IND"
    underlying.exchange = "CBOE"
    underlying.currency = "USD"
    
    # Request market data for the underlying (essential for option computations)
    und_req_id = 1
    app.reqMktData(und_req_id, underlying, "", False, False, [])
    app.logger.info("Requested market data for SPX underlying")
    
    # Wait for underlying data
    time.sleep(2)
    
    # Get tomorrow's expiry (nearest 1DTE)
    today = datetime.date.today()
    if today.weekday() == 4:  # Friday
        next_trading_day = today + datetime.timedelta(days=3)
    else:
        next_trading_day = today + datetime.timedelta(days=1)
    expiry = next_trading_day.strftime("%Y%m%d")
    
    # Create a contract for options chain
    option = Contract()
    option.symbol = "SPX"
    option.secType = "OPT"
    option.exchange = "SMART"
    option.currency = "USD"
    option.lastTradeDateOrContractMonth = expiry
    option.multiplier = "100"
    
    # Request contract details
    app.reqContractDetails(2, option)
    app.logger.info(f"Requested option chain for SPX, expiry {expiry}")
    
    # Wait for contract details
    timeout = 10
    start_time = time.time()
    while not app.contract_details_end and time.time() - start_time < timeout:
        time.sleep(0.1)
    
    # Limit to just a few contracts near the money
    atm_strikes = []
    if len(app.data) > 0:
        # Get current underlying price if available
        # For testing, let's hardcode a value close to current SPX
        current_price = 5950  
        
        # Get a few strikes around the current price
        strikes = sorted(list(set(item['strike'] for item in app.data)))
        
        # Find the closest strike to current price
        closest_strike = min(strikes, key=lambda x: abs(x - current_price))
        idx = strikes.index(closest_strike)
        
        # Get a range of strikes
        start_idx = max(0, idx - 5)
        end_idx = min(len(strikes) - 1, idx + 5)
        selected_strikes = strikes[start_idx:end_idx+1]
        
        app.logger.info(f"Selected strikes around {current_price}: {selected_strikes}")
        
        # Filter to just a few contracts for testing
        test_contracts = []
        for contract_info in app.data:
            if contract_info['strike'] in selected_strikes:
                test_contracts.append(contract_info)
                
        app.logger.info(f"Testing with {len(test_contracts)} options near the money")
        test_data = test_contracts
    else:
        test_data = app.data
    
    # Request market data for option contracts
    app.logger.info("Requesting market data for option contracts...")
    for i, contract_info in enumerate(test_data):
        contract = contract_info['contract']
        req_id = contract.conId
        
        # Use valid generic tick types from the error message
        # 100 = Option Volume
        # 101 = Option Open Interest
        # 106 = impvolat (implied volatility)
        app.reqMktData(req_id, contract, "100,101,106", False, False, [])
        
        app.logger.info(f"Requested data for {contract.right} {contract.strike}, conId={contract.conId}")
        time.sleep(0.2)  # Throttle requests
    
    # Wait for data
    app.logger.info("Waiting for option data...")
    time.sleep(20)
    
    # Show unique callbacks received
    unique_callbacks = set(app.all_callbacks)
    app.logger.info(f"Callbacks received: {unique_callbacks}")
    
    # Show the results
    delta_count = sum(1 for data in app.option_data.values() if 'delta' in data)
    app.logger.info(f"Received delta data for {delta_count}/{len(test_data)} options")
    
    # Get and display sorted call and put options by delta
    calls = []
    puts = []
    
    for req_id, data in app.option_data.items():
        contract_info = next((opt for opt in app.data if opt['contract'].conId == req_id), None)
        if not contract_info:
            continue
            
        option_info = {
            'strike': contract_info['strike'],
            'right': contract_info['contract'].right,
            'delta': data.get('delta'),
            'bid': data.get('bid', 0),
            'ask': data.get('ask', 0)
        }
        
        if contract_info['contract'].right == 'C':
            calls.append(option_info)
        else:
            puts.append(option_info)
    
    # Display all options with prices whether or not they have delta
    app.logger.info("CALLS:")
    for call in sorted(calls, key=lambda x: x['strike']):
        delta_str = f", Delta: {call['delta']:.4f}" if call.get('delta') is not None else ", Delta: MISSING"
        app.logger.info(f"Strike: {call['strike']}{delta_str}, Bid/Ask: {call.get('bid', 0)}/{call.get('ask', 0)}")
    
    app.logger.info("PUTS:")
    for put in sorted(puts, key=lambda x: x['strike']):
        delta_str = f", Delta: {put['delta']:.4f}" if put.get('delta') is not None else ", Delta: MISSING" 
        app.logger.info(f"Strike: {put['strike']}{delta_str}, Bid/Ask: {put.get('bid', 0)}/{put.get('ask', 0)}")
    
    # Cancel all market data requests
    app.cancelMktData(und_req_id)
    for contract_info in test_data:
        app.cancelMktData(contract_info['contract'].conId)
    
    # Disconnect
    app.disconnect()
    api_thread.join()

if __name__ == "__main__":
    main() 