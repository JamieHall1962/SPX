from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ComboLeg
from ibapi.order import Order
from ibapi.tag_value import TagValue
from threading import Thread, Event
import time
from datetime import datetime
import pytz
import requests
from datetime import timedelta
import json
from typing import List
import schedule

class TestWrapper(EWrapper):
    def __init__(self):
        super().__init__()
        self.data = []
        self.chain_complete = Event()
        self.current_price = None
        self.option_data = {}  # Store option data by conId
        self.next_order_id = None  # Add this
        self.order_id_event = Event()  # Add this
        self.order_status = {}  # Track order status
        self.fill_event = Event()  # Add this to track fills
        self.executions = {}  # Track executions

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        print(f'Error {errorCode}: {errorString}')
        if advancedOrderRejectJson:
            print(f"Advanced Info: {advancedOrderRejectJson}")

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib):
        if reqId == 0:  # SPX index
            if tickType == 4:  # Last price during RTH
                self.current_price = price
                print(f"SPX last price: {price}")
            elif tickType == 9:  # Close price
                if not self.current_price:  # Only use close if we don't have last
                    self.current_price = price
                    print(f"SPX close price: {price}")
        else:  # Option prices
            if tickType == 1:  # Bid
                if reqId not in self.option_data:
                    self.option_data[reqId] = {}
                self.option_data[reqId]['bid'] = price
            elif tickType == 2:  # Ask
                if reqId not in self.option_data:
                    self.option_data[reqId] = {}
                self.option_data[reqId]['ask'] = price
                
                # Calculate mid price when we have both bid and ask
                if 'bid' in self.option_data[reqId]:
                    self.option_data[reqId]['mid'] = (self.option_data[reqId]['bid'] + price) / 2

    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        """Handle option computations"""
        if tickType == 13 and delta is not None:
            if reqId not in self.option_data:
                self.option_data[reqId] = {}
            self.option_data[reqId].update({
                'delta': abs(delta),
                'strike': next((opt['strike'] for opt in self.data if opt['contract'].conId == reqId), None),
                'right': next((opt['contract'].right for opt in self.data if opt['contract'].conId == reqId), None)
            })

    def contractDetails(self, reqId, contractDetails):
        """Handle contract details and request market data"""
        contract_data = {
            'contract': contractDetails.contract,
            'strike': contractDetails.contract.strike,
            'bid': 0,
            'ask': 0
        }
        self.data.append(contract_data)
        
        # Request market data for this option
        self.reqMktData(contractDetails.contract.conId, contractDetails.contract, "", False, False, [])

    def contractDetailsEnd(self, reqId):
        """Handle end of contract details"""
        print(f"Contract details request {reqId} completed.")
        print(f"Received {len(self.data)} contracts total.")
        self.chain_complete.set()

    def nextValidId(self, orderId: int):
        """Called by TWS with next valid order ID"""
        super().nextValidId(orderId)
        self.next_order_id = orderId
        self.order_id_event.set()  # Signal we have the ID

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice,
                   permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        """Called when order status changes"""
        self.order_status[orderId] = {
            'status': status,
            'filled': filled,
            'remaining': remaining,
            'avgFillPrice': avgFillPrice,
            'lastFillPrice': lastFillPrice,
            'whyHeld': whyHeld
        }
        print(f"\nOrder {orderId} Status: {status}")
        print(f"Filled: {filled}, Remaining: {remaining}")
        if avgFillPrice:
            print(f"Avg Fill Price: {avgFillPrice}")
        if whyHeld:
            print(f"Why Held: {whyHeld}")
        
        if status == "Filled":
            self.fill_event.set()

    def openOrder(self, orderId, contract, order, orderState):
        """Called when order is submitted/modified"""
        print(f"\nOrder {orderId} {orderState.status}:")
        print(f"  Action: {order.action}")
        print(f"  Quantity: {order.totalQuantity}")
        print(f"  Order Type: {order.orderType}")
        print(f"  Limit Price: {order.lmtPrice}")
        if orderState.commission:
            print(f"  Commission: {orderState.commission}")

    def execDetails(self, reqId, contract, execution):
        """Called when order is executed"""
        print(f"\nExecution: Order {execution.orderId}")
        print(f"  Time: {execution.time}")
        print(f"  Shares: {execution.shares}")
        print(f"  Price: {execution.price}")
        
        # Store execution details
        self.executions[execution.execId] = {
            'orderId': execution.orderId,
            'time': execution.time,
            'shares': execution.shares,
            'price': execution.price
        }

    def commissionReport(self, commissionReport):
        """Called when commission info is available"""
        execId = commissionReport.execId
        if execId in self.executions:
            print(f"  Commission: {commissionReport.commission}")
            self.executions[execId]['commission'] = commissionReport.commission

def round_to_nickel(price):
    """Round a price to the nearest nickel"""
    return round(price * 20) / 20

class TestApp(EClient, TestWrapper):
    def __init__(self, dte):
        TestWrapper.__init__(self)
        EClient.__init__(self, self)
        self.dte = 0  # 0 DTE
        self.data = []
        self.started = False
        self.next_req_id = 1
        self.chain_complete = Event()
        self.price_received = Event()
        self.current_price = None
        self.next_order_id = 1

    def start_connection(self):
        """Connect to TWS/IB Gateway"""
        self.connect("127.0.0.1", 7496, 1)
        print("Connecting to TWS...")
        
        # Start thread for messages
        thread = Thread(target=self.run)
        thread.start()

    def request_current_price(self):
        """Request current SPX price"""
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"

        # Reset price flag and storage
        self.price_received.clear()
        self.current_price = None

        # Request market data
        req_id = self.next_req_id
        self.next_req_id += 1
        self.reqMktData(req_id, contract, "", False, False, [])

    def tickPrice(self, reqId, tickType, price, attrib):
        """Handle price updates"""
        if reqId == 1001 and tickType == 4:  # Last price for SPX
            self.current_price = price
            print(f"SPX price: {price}")
            self.price_received.set()
            
            # Cancel subscription after receiving price
            self.cancelMktData(reqId)
        elif tickType == 1:  # Bid
            for opt in self.data:
                if opt['contract'].conId == reqId:
                    opt['bid'] = price
                    break
        elif tickType == 2:  # Ask
            for opt in self.data:
                if opt['contract'].conId == reqId:
                    opt['ask'] = price
                    break

    def request_options(self):
        """Request options chain and market data"""
        if not self.started:
            return
        
        # Clear previous data
        self.data = []
        
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "OPT"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        contract.tradingClass = "SPXW"  # Add trading class for weeklys
        
        expiry = self.get_expiration_by_dte(self.dte)
        print(f"\nRequesting options chain for expiry: {expiry}")
        contract.lastTradeDateOrContractMonth = expiry
        
        # Request contract details
        self.reqContractDetails(1, contract)

    def get_cboe_calendar(self) -> List[str]:
        """Get CBOE trading calendar from their API"""
        try:
            # CBOE Calendar API endpoint
            url = "https://cdn.cboe.com/api/global/delayed_quotes/calendar_holidays.json"
            
            # Add headers to mimic browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract and format holidays
            holidays = []
            for holiday in data.get('holidays', []):
                date_str = holiday.get('date')
                if date_str:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    holidays.append(date_obj.strftime('%Y%m%d'))
            
            return holidays
            
        except Exception as e:
            print(f"Warning: Could not fetch CBOE calendar: {e}")
            return []

    def get_holidays(self) -> List[str]:
        """Get list of holidays based on current year"""
        current_year = datetime.now().year
        if current_year == 2024:
            return ["20240101", "20240115", "20240219", "20240329", "20240527", "20240619", "20240704", "20240902", "20241128", "20241225"]
        elif current_year == 2025:
            return ["20250101", "20250120", "20250217", "20250418", "20250526", "20250619", "20250704", "20250901", "20251127", "20251225"]
        else:
            print(f"Warning: No holiday data for year {current_year}")
            return []

    def get_expiration_by_dte(self, dte: int) -> str:
        """Get option expiration date string based on DTE"""
        today = datetime.now()
        
        # For 0DTE, use today
        if dte == 0:
            return today.strftime('%Y%m%d')
        
        # Get holidays for current year
        holidays = self.get_holidays()
        
        # Start from today and count business days forward
        business_days = 0
        target_date = today
        while business_days < dte:
            target_date += timedelta(days=1)
            date_str = target_date.strftime('%Y%m%d')
            # Check if it's a business day and not a holiday
            if target_date.weekday() < 5 and date_str not in holidays:
                business_days += 1
        
        return target_date.strftime('%Y%m%d')

    def create_iron_condor_order(self, 
                               short_call_strike: float, 
                               long_call_strike: float,
                               short_put_strike: float,
                               long_put_strike: float,
                               expiry: str,
                               target_credit: float) -> tuple:
        """Create an Iron Condor combo order"""
        
        # Create timestamp for order reference
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        order_ref = f"IC_{timestamp}_{short_put_strike}_{long_put_strike}_{short_call_strike}_{long_call_strike}"
        
        # Create the combo contract
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "BAG"
        contract.currency = "USD"
        contract.exchange = "CBOE"

        # Define the legs
        legs = []
        
        # Short Put
        short_put = ComboLeg()
        short_put.conId = next(opt['contract'].conId for opt in self.data 
                              if opt['contract'].right == 'P' 
                              and opt['contract'].strike == short_put_strike)
        short_put.ratio = 1
        short_put.action = "SELL"
        short_put.exchange = "CBOE"
        legs.append(short_put)

        # Long Put
        long_put = ComboLeg()
        long_put.conId = next(opt['contract'].conId for opt in self.data 
                             if opt['contract'].right == 'P' 
                             and opt['contract'].strike == long_put_strike)
        long_put.ratio = 1
        long_put.action = "BUY"
        long_put.exchange = "CBOE"
        legs.append(long_put)

        # Short Call
        short_call = ComboLeg()
        short_call.conId = next(opt['contract'].conId for opt in self.data 
                               if opt['contract'].right == 'C' 
                               and opt['contract'].strike == short_call_strike)
        short_call.ratio = 1
        short_call.action = "SELL"
        short_call.exchange = "CBOE"
        legs.append(short_call)

        # Long Call
        long_call = ComboLeg()
        long_call.conId = next(opt['contract'].conId for opt in self.data 
                              if opt['contract'].right == 'C' 
                              and opt['contract'].strike == long_call_strike)
        long_call.ratio = 1
        long_call.action = "BUY"
        long_call.exchange = "CBOE"
        legs.append(long_call)

        contract.comboLegs = legs

        # Create the order
        order = Order()
        order.action = "BUY"
        order.totalQuantity = 1
        order.orderType = "LMT"
        order.lmtPrice = -target_credit
        order.orderRef = order_ref
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        
        print(f"\nCreating Iron Condor with reference: {order_ref}")
        return contract, order

    def adjust_price_down(self, current_credit: float) -> float:
        """
        Adjust price down by 1% or minimum of $0.05, whichever is greater
        Returns the new credit amount (positive number)
        """
        # Calculate 1% reduction
        one_percent = self.round_to_nickel(current_credit * 0.99)
        
        # If the change is less than 0.05, force a 0.05 reduction
        if current_credit - one_percent < 0.05:
            return self.round_to_nickel(current_credit - 0.05)
        
        return one_percent

    def manage_iron_condor_order(self, contract, order, target_credit):
        """Manage iron condor order with adjustments"""
        
        def round_to_nickel(price):
            return round(price * 20) / 20
        
        # Initialize tracking variables
        start_time = time.time()
        current_credit = target_credit
        order_id = self.next_order_id
        self.next_order_id += 1
        
        # Place initial order
        print(f"\nPlacing initial order {order.orderRef} at {target_credit} credit...")
        self.placeOrder(order_id, contract, order)
        
        # Track order status
        while True:
            elapsed = time.time() - start_time
            
            # After 5 minutes, cancel and exit
            if elapsed > 300:  # 5 minutes
                print(f"\nReached maximum time (5 minutes). Cancelling order.")
                self.cancelOrder(order_id)
                break
            
            # Adjust credit after 2, 3, and 4 minutes
            if elapsed > 240 and current_credit == target_credit:  # 4 minutes
                new_credit = round_to_nickel(current_credit * 0.97)  # 3% total reduction
                print(f"\nFinal adjustment: reducing credit from {current_credit} to {new_credit}")
            elif elapsed > 180 and current_credit == target_credit:  # 3 minutes
                new_credit = round_to_nickel(current_credit * 0.98)  # 2% total reduction
                print(f"\nSecond adjustment: reducing credit from {current_credit} to {new_credit}")
            elif elapsed > 120 and current_credit == target_credit:  # 2 minutes
                new_credit = round_to_nickel(current_credit * 0.99)  # 1% reduction
                print(f"\nFirst adjustment: reducing credit from {current_credit} to {new_credit}")
            else:
                time.sleep(1)
                continue
            
            # Cancel existing order
            print(f"Cancelling order {order_id}")
            self.cancelOrder(order_id)
            time.sleep(1)  # Wait for cancellation
            
            # Create new order with adjusted credit
            new_order = Order()
            new_order.action = "BUY"
            new_order.totalQuantity = 1
            new_order.orderType = "LMT"
            new_order.lmtPrice = -new_credit  # Negative for credit
            new_order.orderRef = f"{order.orderRef}_ADJ{int(elapsed//60)}"
            new_order.eTradeOnly = False
            new_order.firmQuoteOnly = False
            
            # Get new order ID
            new_order_id = self.next_order_id
            self.next_order_id += 1
            
            print(f"Placing new order {new_order_id} ({new_order.orderRef}) at {new_credit} credit...")
            self.placeOrder(new_order_id, contract, new_order)
            
            # Update tracking variables
            current_credit = new_credit
            order_id = new_order_id
            
            time.sleep(1)

    def analyze_chain(self):
        """Analyze options chain and place trade"""
        if not self.current_price or not self.data:
            print("Missing price data or options chain")
            return
        
        print(f"\nAnalyzing chain with SPX at {self.current_price}")
        
        # Wait for market data
        time.sleep(2)
        
        # Separate puts and calls
        puts = []
        calls = []
        
        for opt in self.data:
            if 'bid' not in opt or 'ask' not in opt:
                continue
            
            # Calculate midpoint
            opt['midpoint'] = (opt['bid'] + opt['ask']) / 2
            
            if opt['contract'].right == 'P':
                puts.append(opt)
            elif opt['contract'].right == 'C':
                calls.append(opt)
        
        if not puts or not calls:
            print("No valid options found")
            return
        
        # Find the put closest to 1.60 and call closest to 1.30
        target_put_price = 1.60
        target_call_price = 1.30
        
        short_put = min(puts, key=lambda x: abs(x['midpoint'] - target_put_price))
        short_call = min(calls, key=lambda x: abs(x['midpoint'] - target_call_price))
        
        short_put_strike = short_put['contract'].strike
        short_call_strike = short_call['contract'].strike
        
        # 30-point wings
        long_put_strike = short_put_strike - 30
        long_call_strike = short_call_strike + 30
        
        # Find the long options
        long_put = next(opt for opt in puts if opt['contract'].strike == long_put_strike)
        long_call = next(opt for opt in calls if opt['contract'].strike == long_call_strike)
        
        # Calculate total credit: (short_put + short_call) - (long_put + long_call)
        total_credit = round_to_nickel(
            (short_put['midpoint'] + short_call['midpoint']) - 
            (long_put['midpoint'] + long_call['midpoint'])
        )
        
        print(f"\nSelected strikes and prices:")
        print(f"Short Put: {short_put_strike} (credit: {short_put['midpoint']:.2f})")
        print(f"Long Put: {long_put_strike} (debit: {long_put['midpoint']:.2f})")
        print(f"Short Call: {short_call_strike} (credit: {short_call['midpoint']:.2f})")
        print(f"Long Call: {long_call_strike} (debit: {long_call['midpoint']:.2f})")
        print(f"Total Credit Target: {total_credit:.2f}")
        
        # Create and place the order
        contract, order = self.create_iron_condor_order(
            short_call_strike=short_call_strike,
            long_call_strike=long_call_strike,
            short_put_strike=short_put_strike,
            long_put_strike=long_put_strike,
            expiry=puts[0]['contract'].lastTradeDateOrContractMonth,
            target_credit=total_credit
        )
        
        print("\nPlacing order...")
        self.manage_iron_condor_order(contract, order, total_credit)

    def start_trading(self):
        """Start the trading process"""
        print("\nStarting trading process...")
        self.started = True
        
        # Request underlying price
        self.req_spx_price()
        
        # Wait for price data
        self.price_received.wait(10)
        
        # Request options chain
        self.request_options()
        
        # Wait for chain to load
        self.chain_complete.wait(30)
        
        # Analyze chain and place trade
        self.analyze_chain()
        
        return

    def schedule_trades(self):
        """Schedule trades for predefined times"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Schedule just once
        schedule.clear()
        schedule.every().day.at("10:00").do(self.start_trading)
        
        print("Trade scheduled for 10:00")
        
        # Run once manually for testing (remove in production)
        self.start_trading()

    def req_spx_price(self):
        """Request SPX price"""
        print("\nRequesting SPX price...")
        
        # Create contract for SPX index
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        
        # Request market data
        self.reqMktData(1001, contract, "", False, False, [])

if __name__ == "__main__":
    dte = 0  # 0 DTE
    app = TestApp(dte)
    app.connect("127.0.0.1", 7496, 1)
    
    # Start thread for messages
    thread = Thread(target=app.run)
    thread.start()
    
    time.sleep(1)
    
    # Start scheduling - but don't run the loop
    print("\nStarting trade scheduler...")
    app.schedule_trades()
    
    # Don't enter the scheduler loop for testing
    # while True:
    #     schedule.run_pending()
    #     time.sleep(1)
