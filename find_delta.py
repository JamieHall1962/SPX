from tws_connector import TWSConnector, OptionPosition
import time
from datetime import datetime, timedelta
import pytz
from trade_scheduler import TradeScheduler
from trade_config import TradeConfig, DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3, DC_CONFIG_4, DC_CONFIG_5, DC_CONFIG_6
from trade_database import TradeDatabase
import sys
import threading
from typing import Optional
import queue

def is_market_hours():
    """Check if we can get quotes (20:15 - 16:00 ET, Mon-Fri)"""
    et_time = datetime.now(pytz.timezone('US/Eastern'))
    
    # Check if it's a weekday
    if et_time.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    
    # Convert time to decimal hours for easier comparison
    hour_dec = et_time.hour + et_time.minute/60
    
    # Can get quotes during:
    # - Regular Trading Hours (RTH): 9:30 AM - 4:00 PM ET
    # - Extended Hours: 8:15 PM - 9:15 AM ET next day
    return (20.25 <= hour_dec <= 24.0) or (0.0 <= hour_dec <= 16.0)

def get_expiry_from_dte(dte: int) -> str:
    """Calculate the expiry date string from DTE (Days To Expiry)"""
    et_time = datetime.now(pytz.timezone('US/Eastern'))
    
    # If after 4:15 PM ET, start counting from tomorrow
    if et_time.hour > 16 or (et_time.hour == 16 and et_time.minute >= 15):
        et_time += timedelta(days=1)
    
    # Add the DTE to get target expiry
    expiry_date = et_time + timedelta(days=dte)
    
    # Skip to next weekday if it lands on weekend
    while expiry_date.weekday() > 4:  # 5 = Saturday, 6 = Sunday
        expiry_date += timedelta(days=1)
        
    return expiry_date.strftime('%Y%m%d')

def find_target_delta_option(tws: TWSConnector, expiry: str, right: str, initial_strike: float, target_delta: float = 0.15) -> Optional[OptionPosition]:
    """Find an option with a target delta or premium using binary search"""
    print(f"\nLooking for {right} option with target delta/premium: {target_delta}")
    
    # Determine if we're searching by delta or premium
    searching_by_premium = target_delta > 1.0
    search_type = "premium" if searching_by_premium else "delta"
    print(f"Searching by {search_type}")
    
    # For puts searching by premium, adjust initial strike based on DTE
    if searching_by_premium:
        current_spx = tws.spx_price  # Get current SPX price
        print(f"Current SPX price: {current_spx}")
        
        if expiry == get_expiry_from_dte(0):  # If it's 0DTE
            # For 0DTE puts targeting $1.60, start slightly OTM
            # For 0DTE calls targeting $1.30, start slightly OTM
            if right == "P":
                # Start about 20-30 points BELOW current price for puts
                initial_strike = round((current_spx - 25) / 5) * 5
                strike_increment = 5  # Use 5-point increments
            else:  # Calls
                # Start about 20-30 points ABOVE current price for calls
                initial_strike = round((current_spx + 25) / 5) * 5
                strike_increment = 5  # Use 5-point increments
            print(f"0DTE option - starting at strike {initial_strike} ({'+' if initial_strike > current_spx else '-'}{abs(initial_strike - current_spx)} points from current price)")
        else:
            # For longer dated options, can start further OTM
            if right == "P":
                initial_strike = round((current_spx - 50) / 5) * 5
            else:
                initial_strike = round((current_spx + 50) / 5) * 5
            strike_increment = 5
    else:
        strike_increment = 5  # Standard increment for delta-based search
    
    # Get initial option chain
    options = tws.request_option_chain(expiry, right, initial_strike, initial_strike)
    if not options:
        print("No options found")
        return None
        
    # Get initial option's delta or premium
    if searching_by_premium:
        # Request bid/ask for accurate pricing
        req_id = tws.get_next_req_id()
        tws.reqMktData(req_id, options[0].contract, "100,101", False, False, [])  # Request bid/ask
        
        # Wait for bid/ask data
        bid = ask = None
        timeout = time.time() + 2
        while time.time() < timeout and (bid is None or ask is None):
            try:
                msg = tws.data_queue.get(timeout=0.1)
                if msg[0] == 'price' and msg[1] == req_id:
                    if msg[2] == 1:  # Bid
                        bid = msg[3]
                    elif msg[2] == 2:  # Ask
                        ask = msg[3]
            except queue.Empty:
                continue
        
        tws.cancelMktData(req_id)
        
        if bid is not None and ask is not None:
            current_value = round(((bid + ask) / 2) * 20) / 20  # Round to nearest 0.05
            print(f"Initial {right} option price: {current_value:.2f} (bid: {bid:.2f}, ask: {ask:.2f})")
        else:
            print("Failed to get bid/ask data")
            return None
    else:
        current_value = options[0].delta if options[0].delta is not None else 0
        print(f"Initial {right} option delta: {current_value:.3f}")
    
    # Initialize search variables
    best_option = options[0]
    best_diff = abs(current_value - target_delta)
    
    # For premium-based search, we'll track options above and below target
    if searching_by_premium:
        # Search both up and down from initial strike
        current_strike = initial_strike
        all_options = []  # Store all options we find
        max_strikes = 20  # Maximum number of strikes to check in each direction
        
        # Search downward (higher premium for puts, lower for calls)
        for i in range(max_strikes):
            strike = current_strike - (i * strike_increment)
            options = tws.request_option_chain(expiry, right, strike, strike)
            if options:
                # Get accurate pricing using bid/ask
                req_id = tws.get_next_req_id()
                tws.reqMktData(req_id, options[0].contract, "100,101", False, False, [])
                
                bid = ask = None
                timeout = time.time() + 2
                while time.time() < timeout and (bid is None or ask is None):
                    try:
                        msg = tws.data_queue.get(timeout=0.1)
                        if msg[0] == 'price' and msg[1] == req_id:
                            if msg[2] == 1:  # Bid
                                bid = msg[3]
                            elif msg[2] == 2:  # Ask
                                ask = msg[3]
                    except queue.Empty:
                        continue
                
                tws.cancelMktData(req_id)
                
                if bid is not None and ask is not None:
                    premium = round(((bid + ask) / 2) * 20) / 20  # Round to nearest 0.05
                    print(f"Strike {strike}: premium = {premium:.2f} (bid: {bid:.2f}, ask: {ask:.2f})")
                    all_options.append((options[0], premium))
                    if premium > target_delta * 1.5:  # Stop if premium gets too high
                        break
        
        # Search upward (lower premium for puts, higher for calls)
        for i in range(1, max_strikes):  # Start at 1 to skip initial strike
            strike = current_strike + (i * strike_increment)
            options = tws.request_option_chain(expiry, right, strike, strike)
            if options:
                # Get accurate pricing using bid/ask
                req_id = tws.get_next_req_id()
                tws.reqMktData(req_id, options[0].contract, "100,101", False, False, [])
                
                bid = ask = None
                timeout = time.time() + 2
                while time.time() < timeout and (bid is None or ask is None):
                    try:
                        msg = tws.data_queue.get(timeout=0.1)
                        if msg[0] == 'price' and msg[1] == req_id:
                            if msg[2] == 1:  # Bid
                                bid = msg[3]
                            elif msg[2] == 2:  # Ask
                                ask = msg[3]
                    except queue.Empty:
                        continue
                
                tws.cancelMktData(req_id)
                
                if bid is not None and ask is not None:
                    premium = round(((bid + ask) / 2) * 20) / 20  # Round to nearest 0.05
                    print(f"Strike {strike}: premium = {premium:.2f} (bid: {bid:.2f}, ask: {ask:.2f})")
                    all_options.append((options[0], premium))
                    if premium < target_delta * 0.5:  # Stop if premium gets too low
                        break
        
        # Find option with premium closest to target
        if all_options:
            best_option, _ = min(all_options, key=lambda x: abs(x[1] - target_delta))
            # Get final bid/ask for best option
            req_id = tws.get_next_req_id()
            tws.reqMktData(req_id, best_option.contract, "100,101", False, False, [])
            
            bid = ask = None
            timeout = time.time() + 2
            while time.time() < timeout and (bid is None or ask is None):
                try:
                    msg = tws.data_queue.get(timeout=0.1)
                    if msg[0] == 'price' and msg[1] == req_id:
                        if msg[2] == 1:  # Bid
                            bid = msg[3]
                        elif msg[2] == 2:  # Ask
                            ask = msg[3]
                except queue.Empty:
                    continue
            
            tws.cancelMktData(req_id)
            
            if bid is not None and ask is not None:
                best_diff = abs(round(((bid + ask) / 2) * 20) / 20 - target_delta)
    
    if best_option:
        if searching_by_premium:
            # Get final bid/ask for display
            req_id = tws.get_next_req_id()
            tws.reqMktData(req_id, best_option.contract, "100,101", False, False, [])
            
            bid = ask = None
            timeout = time.time() + 2
            while time.time() < timeout and (bid is None or ask is None):
                try:
                    msg = tws.data_queue.get(timeout=0.1)
                    if msg[0] == 'price' and msg[1] == req_id:
                        if msg[2] == 1:  # Bid
                            bid = msg[3]
                        elif msg[2] == 2:  # Ask
                            ask = msg[3]
                except queue.Empty:
                    continue
            
            tws.cancelMktData(req_id)
            
            if bid is not None and ask is not None:
                final_value = round(((bid + ask) / 2) * 20) / 20  # Round to nearest 0.05
                print(f"\nFound {right} option:")
                print(f"Strike: {best_option.contract.strike}")
                print(f"Premium: {final_value:.2f} (bid: {bid:.2f}, ask: {ask:.2f}, target: {target_delta:.2f})")
                best_option.market_price = final_value  # Store the price
        else:
            print(f"\nFound {right} option:")
            print(f"Strike: {best_option.contract.strike}")
            print(f"Delta: {best_option.delta:.3f} (target: {target_delta:.3f})")
            
        # Set up exit monitoring if this is a short option with premium > 1.0
        if searching_by_premium:
            best_option.exit_price = best_option.contract.strike + (2 if right == "P" else -2)
    
    return best_option

def execute_iron_condor(tws: TWSConnector = None):
    """Execute the iron condor trade strategy"""
    # Create TWS connection if not provided
    if tws is None:
        tws = TWSConnector(client_id=99)
        try:
            print("Connecting to TWS...")
            tws.connect()
            time.sleep(1)
        except:
            print("Failed to connect to TWS")
            return
    
    try:
        # Get SPX price based on market hours
        if is_market_hours():
            print("Market is open - getting real-time price...")
            tws.request_spx_data()
            timeout = time.time() + 3
            while tws.spx_price is None and time.time() < timeout:
                time.sleep(0.1)
        else:
            print("Market is closed - getting previous closing price...")
            tws.request_spx_historical_data()
            timeout = time.time() + 3
            while tws.spx_price is None and time.time() < timeout:
                time.sleep(0.1)
        
        if tws.spx_price is None:
            print("Failed to get SPX price")
            return
            
        spx_price = tws.spx_price
        print(f"\nSPX Price: {spx_price:.2f}")
        
        # Get expiry for 1DTE
        expiry = get_expiry_from_dte(1)
        print(f"\nLooking for {1}DTE options (expiry: {expiry})")
        
        # Find 0.06 delta call (more OTM)
        call_strike = round((spx_price + 50) / 5) * 5  # Start ~50 points OTM
        call_option = find_target_delta_option(tws, expiry, "C", call_strike, target_delta=0.06)
        
        # Find 0.20 delta put (less OTM)
        put_strike = round((spx_price - 50) / 5) * 5  # Start ~50 points OTM
        put_option = find_target_delta_option(tws, expiry, "P", put_strike, target_delta=0.20)
        
        # Print final summary with prices
        print("\n" + "="*50)
        print("🎯 FINAL RESULTS")
        print("="*50)
        print(f"SPX Price: {spx_price:.2f}")
        print(f"Expiry: {expiry} (1DTE)")
        print("-"*50)
        
        if call_option:
            # Get price for call
            call_price = tws.get_option_price(call_option.contract)
            
            # Get the call wing (20 points higher)
            call_wing_strike = round((call_option.contract.strike + 20) / 5) * 5
            print(f"\nGetting call wing at strike {call_wing_strike}...")
            call_wing_options = tws.request_option_chain(expiry, "C", call_wing_strike, call_wing_strike)
            if call_wing_options:
                call_wing = call_wing_options[0]
                call_wing_price = tws.get_option_price(call_wing.contract)
            else:
                print("Failed to get call wing option")
                call_wing = None
                call_wing_price = 0
            
            print("\n📞 CALL SPREAD:")
            print(f"   Short Strike: {call_option.contract.strike}")
            print(f"   Short Delta: {call_option.delta:.4f}")
            print(f"   Short IV: {call_option.implied_vol:.4f}")
            print(f"   Short Price: {call_price:.2f}")
            print(f"   Short Symbol: {call_option.contract.localSymbol}")
            if call_wing:
                print(f"   Long Strike: {call_wing.contract.strike}")
                print(f"   Long Delta: {call_wing.delta:.4f}")
                print(f"   Long IV: {call_wing.implied_vol:.4f}")
                print(f"   Long Price: {call_wing_price:.2f}")
                print(f"   Long Symbol: {call_wing.contract.localSymbol}")
                print(f"   Net Credit: {(call_price - call_wing_price):.2f}")
            else:
                print("   Failed to get long call details")
        else:
            print("\n❌ No suitable call option found")
            
        if put_option:
            # Get price for put
            put_price = tws.get_option_price(put_option.contract)
            
            # Get the put wing (20 points lower)
            put_wing_strike = round((put_option.contract.strike - 20) / 5) * 5
            print(f"\nGetting put wing at strike {put_wing_strike}...")
            put_wing_options = tws.request_option_chain(expiry, "P", put_wing_strike, put_wing_strike)
            if put_wing_options:
                put_wing = put_wing_options[0]
                put_wing_price = tws.get_option_price(put_wing.contract)
            else:
                print("Failed to get put wing option")
                put_wing = None
                put_wing_price = 0
            
            print("\n📉 PUT SPREAD:")
            print(f"   Short Strike: {put_option.contract.strike}")
            print(f"   Short Delta: {put_option.delta:.4f}")
            print(f"   Short IV: {put_option.implied_vol:.4f}")
            print(f"   Short Price: {put_price:.2f}")
            print(f"   Short Symbol: {put_option.contract.localSymbol}")
            if put_wing:
                print(f"   Long Strike: {put_wing.contract.strike}")
                print(f"   Long Delta: {put_wing.delta:.4f}")
                print(f"   Long IV: {put_wing.implied_vol:.4f}")
                print(f"   Long Price: {put_wing_price:.2f}")
                print(f"   Long Symbol: {put_wing.contract.localSymbol}")
                print(f"   Net Credit: {(put_price - put_wing_price):.2f}")
            else:
                print("   Failed to get long put details")
        else:
            print("\n❌ No suitable put option found")
            
        if call_option and put_option and call_wing and put_wing:
            total_credit = (call_price - call_wing_price) + (put_price - put_wing_price)
            print(f"\n💰 Total Net Credit: {total_credit:.2f}")
            
            # Add clear summary of the complete iron condor
            print("\n" + "="*50)
            print("🦅 IRON CONDOR SUMMARY")
            print("="*50)
            print(f"Expiry: {expiry} (1DTE)")
            print(f"SPX Price: {spx_price:.2f}")
            print("\nShort Put Spread:")
            print(f"    {put_wing.contract.strike:.0f} Long Put  @ {put_wing_price:.2f}")
            print(f"    {put_option.contract.strike:.0f} Short Put @ {put_price:.2f}")
            print(f"    Credit: {(put_price - put_wing_price):.2f}")
            
            print("\nShort Call Spread:")
            print(f"    {call_option.contract.strike:.0f} Short Call @ {call_price:.2f}")
            print(f"    {call_wing.contract.strike:.0f} Long Call  @ {call_wing_price:.2f}")
            print(f"    Credit: {(call_price - call_wing_price):.2f}")
            
            print("\nTotal Structure:")
            print(f"    Total Credit: {total_credit:.2f}")
            print(f"    Max Risk: {20:.0f} points = ${2000:.0f}")
            print(f"    Break-even Points: {put_option.contract.strike - total_credit:.0f} and {call_option.contract.strike + total_credit:.0f}")
            
            # Submit the order
            order_id = tws.submit_iron_condor(
                put_wing_contract=put_wing.contract,
                put_contract=put_option.contract,
                call_contract=call_option.contract,
                call_wing_contract=call_wing.contract,
                quantity=3,
                total_credit=total_credit
            )
            
            print(f"\nOrder submitted with ID: {order_id}")
            print("Monitoring order status for 5 minutes with price adjustments...")
            
            start_time = time.time()
            original_credit = total_credit
            
            # First 2 minutes with original price
            if not tws.monitor_order(order_id, timeout_seconds=120):
                print("\nNot filled after 2 minutes, increasing bid by 0.05...")
                # Cancel existing order
                tws.cancel_order(order_id)
                time.sleep(1)  # Wait for cancellation
                
                # Submit new order with higher bid (less negative credit)
                total_credit = original_credit - 0.05  # Subtract to make less negative
                order_id = tws.submit_iron_condor(
                    put_wing_contract=put_wing.contract,
                    put_contract=put_option.contract,
                    call_contract=call_option.contract,
                    call_wing_contract=call_wing.contract,
                    quantity=3,
                    total_credit=total_credit
                )
                print(f"New order submitted with ID: {order_id} at credit: {total_credit:.2f}")
                
                # Next 2 minutes with first price increase
                if not tws.monitor_order(order_id, timeout_seconds=120):
                    print("\nNot filled after 4 minutes, increasing bid by another 0.05...")
                    # Cancel existing order
                    tws.cancel_order(order_id)
                    time.sleep(1)  # Wait for cancellation
                    
                    # Submit final order with highest bid (least negative credit)
                    total_credit = original_credit - 0.10  # Subtract to make less negative
                    order_id = tws.submit_iron_condor(
                        put_wing_contract=put_wing.contract,
                        put_contract=put_option.contract,
                        call_contract=call_option.contract,
                        call_wing_contract=call_wing.contract,
                        quantity=3,
                        total_credit=total_credit
                    )
                    print(f"Final order submitted with ID: {order_id} at credit: {total_credit:.2f}")
                    
                    # Final 1 minute with highest price
                    if not tws.monitor_order(order_id, timeout_seconds=60):
                        print("\nNot filled after 5 minutes, canceling order...")
                        tws.cancel_order(order_id)
                        print("\nOrder cancelled after all attempts")
            
        print("\n" + "="*50)
        
    finally:
        if tws is None:  # Only disconnect if we created the connection
            print("\nDisconnecting from TWS...")
            tws.disconnect()

class ConnectionManager:
    def __init__(self, client_id=99, check_interval=180, stop_event=None):  # Check every 3 minutes
        self.client_id = client_id
        self.check_interval = check_interval
        self.stop_event = stop_event
        self.tws = None
        self.last_check = 0
        self.db = TradeDatabase()  # Initialize database
        self.connection_attempts = 0
        self.max_attempts_before_restart = 3
        self.connect_with_retry()
    
    def connect_with_retry(self, max_retries=5, retry_delay=10):
        """Establish connection to TWS with retries"""
        self.connection_attempts += 1
        retry_count = 0
        
        while retry_count < max_retries:
            if self.stop_event and self.stop_event.is_set():
                print("\nStop requested during connection attempt")
                return False
                
            try:
                print(f"\nAttempting to connect to TWS (attempt {retry_count + 1}/{max_retries})...")
                if self.connect():
                    print("Successfully connected to TWS")
                    self.connection_attempts = 0  # Reset counter on successful connection
                    return True
                    
                # If we get here, connect() returned False
                if self.connection_attempts >= self.max_attempts_before_restart:
                    print("\n⚠️ CRITICAL: Multiple connection attempts failed!")
                    print("This usually means TWS/IB Gateway needs to be restarted.")
                    print("Please:")
                    print("1. Close Cursor")
                    print("2. Restart TWS/IB Gateway")
                    print("3. Wait 30 seconds")
                    print("4. Restart Cursor")
                    print("\nWaiting for 60 seconds before next attempt...")
                    time.sleep(60)
                    self.connection_attempts = 0  # Reset counter
                    
            except Exception as e:
                print(f"Connection attempt {retry_count + 1} failed: {str(e)}")
            
            retry_count += 1
            if retry_count < max_retries:
                print(f"Waiting {retry_delay} seconds before next attempt...")
                time.sleep(retry_delay)
        
        print("Failed to connect after all retries")
        return False
    
    def connect(self):
        """Establish connection to TWS"""
        try:
            # If we have an existing TWS instance, try to clean it up
            if self.tws is not None:
                try:
                    self.tws.disconnect()
                except:
                    pass
                time.sleep(1)  # Give TWS time to clean up the old connection
                self.tws = None
            
            # Create fresh TWS instance
            self.tws = TWSConnector(client_id=self.client_id)
            
            # Connect with proper cleanup timing
            print("\nConnecting to TWS...")
            self.tws.connect()
            
            # Wait for nextValidId and full initialization
            timeout = time.time() + 10  # 10 second timeout
            while time.time() < timeout:
                if self.tws.isConnected() and self.tws.next_order_id is not None:
                    # Additional wait for complete initialization
                    time.sleep(2)
                    return True
                time.sleep(0.1)
            
            # If we get here, connection failed or nextValidId wasn't received
            print("Connection failed: Did not receive initialization confirmation")
            self.tws = None
            return False
            
        except Exception as e:
            print(f"Connection error: {str(e)}")
            # Clean up failed connection
            if self.tws is not None:
                try:
                    self.tws.disconnect()
                except:
                    pass
                self.tws = None
            return False
    
    def check_connection(self):
        """Check connection status and reconnect if needed"""
        current_time = time.time()
        
        # Only check every check_interval seconds
        if current_time - self.last_check < self.check_interval:
            # Still do a quick check of connection status
            if self.tws and self.tws.isConnected():
                return True
            print("\nConnection lost between regular checks")
        
        self.last_check = current_time
        
        if not self.tws or not self.tws.isConnected():
            print("\nConnection lost, attempting to reconnect...")
            return self.connect_with_retry()
        
        return True
    
    def get_tws(self):
        """Get the TWS connection, checking/reconnecting if needed"""
        if self.check_connection():
            return self.tws
        return None
    
    def disconnect(self):
        """Gracefully disconnect from TWS"""
        if self.tws and self.tws.isConnected():
            print("\nDisconnecting from TWS...")
            self.tws.disconnect()
            self.tws = None

def execute_double_calendar(connection_manager: ConnectionManager, config: TradeConfig = DC_CONFIG):
    """Execute a double calendar trade strategy"""
    tws = connection_manager.get_tws()
    if not tws:
        connection_manager.db.record_trade_attempt(
            config=config,
            spx_price=None,
            status="FAILED",
            reason_if_failed="No TWS connection available"
        )
        print("No TWS connection available")
        return
    
    try:
        # Get SPX price with retries
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            # Check connection before each major operation
            tws = connection_manager.get_tws()
            if not tws:
                connection_manager.db.record_trade_attempt(
                    config=config,
                    spx_price=None,
                    status="FAILED",
                    reason_if_failed="Lost connection during price retrieval"
                )
                print("Lost connection during price retrieval")
                return
                
            if is_market_hours():
                print("Market is open - getting real-time price...")
                tws.request_spx_data()
            else:
                print("Market is closed - getting previous closing price...")
                tws.request_spx_historical_data()
            
            timeout = time.time() + 5
            while tws.spx_price is None and time.time() < timeout:
                time.sleep(0.1)
            
            if tws.spx_price is not None:
                break
                
            retry_count += 1
            print(f"Retry {retry_count}/{max_retries} getting SPX price...")
            time.sleep(2)
        
        if tws.spx_price is None:
            connection_manager.db.record_trade_attempt(
                config=config,
                spx_price=None,
                status="FAILED",
                reason_if_failed="Failed to get SPX price after all retries"
            )
            print("Failed to get SPX price after all retries")
            return
            
        spx_price = tws.spx_price
        print(f"\nSPX Price: {spx_price:.2f}")
        
        # Start recording trade attempt
        trade_id = connection_manager.db.record_trade_attempt(
            config=config,
            spx_price=spx_price,
            status="STARTED"
        )
        
        # Get expiries
        short_expiry = get_expiry_from_dte(config.short_dte)
        put_long_expiry = get_expiry_from_dte(config.put_long_dte)
        call_long_expiry = get_expiry_from_dte(config.call_long_dte)
        
        print(f"\nLooking for options:")
        print(f"Short DTE: {config.short_dte} (expiry: {short_expiry})")
        print(f"Put Long DTE: {config.put_long_dte} (expiry: {put_long_expiry})")
        print(f"Call Long DTE: {config.call_long_dte} (expiry: {call_long_expiry})")
        
        # Find short options with retries
        initial_put_strike = round((spx_price - 50) / 5) * 5  # Round to nearest 5
        initial_call_strike = round((spx_price + 50) / 5) * 5  # Round to nearest 5
        
        print("\nFinding short options...")
        short_put = find_target_delta_option(tws, short_expiry, "P", initial_put_strike, target_delta=config.put_delta)
        if not short_put:
            print("Failed to find short put option")
            return
            
        short_call = find_target_delta_option(tws, short_expiry, "C", initial_call_strike, target_delta=config.call_delta)
        if not short_call:
            print("Failed to find short call option")
            return
            
        # Find long options at same strikes (if offset is 0) or offset strikes
        long_put_strike = short_put.contract.strike - config.put_width
        long_call_strike = short_call.contract.strike + config.call_width
        
        print(f"\nGetting long put at strike {long_put_strike}...")
        retry_count = 0
        while retry_count < max_retries:
            long_put_options = tws.request_option_chain(put_long_expiry, "P", long_put_strike, long_put_strike)
            if long_put_options:
                break
            retry_count += 1
            print(f"Retry {retry_count}/{max_retries} getting long put...")
            time.sleep(2)  # Wait before retry
            
        if not long_put_options:
            print("Failed to get long put after all retries")
            return
        long_put = long_put_options[0]
        
        print(f"\nGetting long call at strike {long_call_strike}...")
        retry_count = 0
        while retry_count < max_retries:
            long_call_options = tws.request_option_chain(call_long_expiry, "C", long_call_strike, long_call_strike)
            if long_call_options:
                break
            retry_count += 1
            print(f"Retry {retry_count}/{max_retries} getting long call...")
            time.sleep(2)  # Wait before retry
            
        if not long_call_options:
            print("Failed to get long call after all retries")
            return
        long_call = long_call_options[0]
        
        # Get prices
        short_put_price = tws.get_option_price(short_put.contract)
        short_call_price = tws.get_option_price(short_call.contract)
        long_put_price = tws.get_option_price(long_put.contract)
        long_call_price = tws.get_option_price(long_call.contract)
        
        # Calculate total debit
        total_debit = (long_put_price - short_put_price) + (long_call_price - short_call_price)
        
        # Print summary
        print("\n" + "="*50)
        print("📅 DOUBLE CALENDAR SUMMARY")
        print("="*50)
        print(f"SPX Price: {spx_price:.2f}")
        
        print("\nPut Side:")
        print(f"    Short {config.short_dte}D Put @ {short_put.contract.strike:.0f} for {short_put_price:.2f}")
        print(f"    Long {config.put_long_dte}D Put @ {long_put.contract.strike:.0f} for {long_put_price:.2f}")
        print(f"    Put Debit: {(long_put_price - short_put_price):.2f}")
        
        print("\nCall Side:")
        print(f"    Short {config.short_dte}D Call @ {short_call.contract.strike:.0f} for {short_call_price:.2f}")
        print(f"    Long {config.call_long_dte}D Call @ {long_call.contract.strike:.0f} for {long_call_price:.2f}")
        print(f"    Call Debit: {(long_call_price - short_call_price):.2f}")
        
        print(f"\nTotal Debit: {total_debit:.2f}")
        
        # Record option legs
        connection_manager.db.record_option_leg(trade_id, "short_put", short_put)
        connection_manager.db.record_option_leg(trade_id, "long_put", long_put)
        connection_manager.db.record_option_leg(trade_id, "short_call", short_call)
        connection_manager.db.record_option_leg(trade_id, "long_call", long_call)
        
        # Submit the order
        order_id = tws.submit_double_calendar(
            short_put_contract=short_put.contract,
            long_put_contract=long_put.contract,
            short_call_contract=short_call.contract,
            long_call_contract=long_call.contract,
            quantity=config.quantity,
            total_debit=total_debit
        )
        
        # Update trade attempt with initial order details
        connection_manager.db.record_trade_attempt(
            config=config,
            spx_price=spx_price,
            status="ORDER_SUBMITTED",
            initial_debit=total_debit,
            order_id=order_id
        )
        
        print(f"\nOrder submitted with ID: {order_id}")
        print("Monitoring order status for 5 minutes with price adjustments...")
        
        start_time = time.time()
        original_debit = total_debit
        
        # First minute with original price
        if not tws.monitor_order(order_id, timeout_seconds=config.initial_wait):
            # Calculate 1% of original debit, rounded to nearest 0.05
            increment = round(abs(original_debit) * config.price_increment_pct * 20) / 20
            print(f"\nNot filled after 1 minute, increasing debit by {increment:.2f} (1%)...")
            
            # Record price adjustment
            connection_manager.db.record_price_adjustment(
                trade_id,
                old_debit=total_debit,
                new_debit=total_debit + increment,
                adjustment_number=1
            )
            
            # Cancel existing order
            tws.cancel_order(order_id)
            time.sleep(1)  # Wait for cancellation
            
            # Submit new order with higher debit
            total_debit = original_debit + increment
            order_id = tws.submit_double_calendar(
                short_put_contract=short_put.contract,
                long_put_contract=long_put.contract,
                short_call_contract=short_call.contract,
                long_call_contract=long_call.contract,
                quantity=config.quantity,
                total_debit=total_debit
            )
            print(f"New order submitted with ID: {order_id} at debit: {total_debit:.2f}")
            
            # Second minute with first price increase
            if not tws.monitor_order(order_id, timeout_seconds=config.second_wait):
                print(f"\nNot filled after 2 minutes, increasing debit by another {increment:.2f} (2%)...")
                # Cancel existing order
                tws.cancel_order(order_id)
                time.sleep(1)  # Wait for cancellation
                
                # Submit order with second increase
                total_debit = original_debit + (2 * increment)
                order_id = tws.submit_double_calendar(
                    short_put_contract=short_put.contract,
                    long_put_contract=long_put.contract,
                    short_call_contract=short_call.contract,
                    long_call_contract=long_call.contract,
                    quantity=config.quantity,
                    total_debit=total_debit
                )
                print(f"New order submitted with ID: {order_id} at debit: {total_debit:.2f}")
                
                # Third minute with second price increase
                if not tws.monitor_order(order_id, timeout_seconds=config.third_wait):
                    print(f"\nNot filled after 3 minutes, increasing debit by another {increment:.2f} (3%)...")
                    # Cancel existing order
                    tws.cancel_order(order_id)
                    time.sleep(1)  # Wait for cancellation
                    
                    # Submit order with third increase
                    total_debit = original_debit + (3 * increment)
                    order_id = tws.submit_double_calendar(
                        short_put_contract=short_put.contract,
                        long_put_contract=long_put.contract,
                        short_call_contract=short_call.contract,
                        long_call_contract=long_call.contract,
                        quantity=config.quantity,
                        total_debit=total_debit
                    )
                    print(f"New order submitted with ID: {order_id} at debit: {total_debit:.2f}")
                    
                    # Fourth minute with third price increase
                    if not tws.monitor_order(order_id, timeout_seconds=config.fourth_wait):
                        print(f"\nNot filled after 4 minutes, increasing debit by another {increment:.2f} (4%)...")
                        # Cancel existing order
                        tws.cancel_order(order_id)
                        time.sleep(1)  # Wait for cancellation
                        
                        # Submit final order with highest debit
                        total_debit = original_debit + (4 * increment)
                        order_id = tws.submit_double_calendar(
                            short_put_contract=short_put.contract,
                            long_put_contract=long_put.contract,
                            short_call_contract=short_call.contract,
                            long_call_contract=long_call.contract,
                            quantity=config.quantity,
                            total_debit=total_debit
                        )
                        print(f"Final order submitted with ID: {order_id} at debit: {total_debit:.2f}")
                        
                        # Final minute with highest price
                        if not tws.monitor_order(order_id, timeout_seconds=config.final_wait):
                            print("\nNot filled after 5 minutes, canceling order...")
                            tws.cancel_order(order_id)
                            print("\nOrder cancelled after all attempts")
            
            # If we reach here, the order was not filled after all attempts
            connection_manager.db.record_trade_attempt(
                config=config,
                spx_price=spx_price,
                status="NOT_FILLED",
                reason_if_failed="Not filled after all price adjustments",
                initial_debit=original_debit,
                final_debit=total_debit,
                order_id=order_id
            )
        else:
            # Order was filled
            fill_time = datetime.now(pytz.timezone('US/Eastern')).isoformat()
            connection_manager.db.record_trade_attempt(
                config=config,
                spx_price=spx_price,
                status="FILLED",
                initial_debit=original_debit,
                final_debit=total_debit,
                fill_time=fill_time,
                order_id=order_id
            )
        
        print("\n" + "="*50)
        
    except Exception as e:
        # Record any unexpected errors
        connection_manager.db.record_trade_attempt(
            config=config,
            spx_price=spx_price if 'spx_price' in locals() else None,
            status="ERROR",
            reason_if_failed=str(e)
        )
        raise

def execute_dc_config_2(connection_manager):
    """Wrapper function to execute DC_CONFIG_2"""
    return execute_double_calendar(connection_manager, config=DC_CONFIG_2)

def execute_dc_config_3(connection_manager):
    """Wrapper function to execute DC_CONFIG_3"""
    return execute_double_calendar(connection_manager, config=DC_CONFIG_3)

def execute_dc_config_4(connection_manager):
    """Wrapper function to execute DC_CONFIG_4"""
    return execute_double_calendar(connection_manager, config=DC_CONFIG_4)

def execute_dc_config_5(connection_manager):
    """Wrapper function to execute DC_CONFIG_5"""
    return execute_double_calendar(connection_manager, config=DC_CONFIG_5)

def execute_dc_config_6(connection_manager):
    """Wrapper function to execute DC_CONFIG_6"""
    return execute_double_calendar(connection_manager, config=DC_CONFIG_6)

def check_recent_trades():
    """Check the most recent trades in the database"""
    db = TradeDatabase()
    print("\nQuerying recent trades...")
    recent_trades = db.get_recent_trades(limit=5)
    print(f"Found {len(recent_trades)} trades")
    
    if not recent_trades:
        print("No trades found in database")
        return
        
    print("\nMost Recent Trades:")
    for trade_details in recent_trades:
        db.print_trade_summary(trade_details)

def main(stop_event=None, message_queue=None):
    """Main function that sets up the scheduler and connection manager"""
    start_time = time.time()  # Track system uptime
    last_check = time.time()
    last_status_check = time.time()  # For more frequent status updates
    consecutive_failures = 0
    max_consecutive_failures = 3
    
    def log_message(msg):
        """Log a message to console and queue if available"""
        print(msg)
        if message_queue:
            message_queue.put(msg)
    
    def update_status(connection_manager, scheduler):
        """Send a status update to the dashboard"""
        if not message_queue:
            return
            
        et_now = datetime.now(pytz.timezone('US/Eastern'))
        is_connected = False
        
        if connection_manager and connection_manager.tws:
            try:
                is_connected = (connection_manager.tws.isConnected() and 
                              connection_manager.tws.next_order_id is not None)
            except:
                is_connected = False
        
        connection_status = "✅ CONNECTED" if is_connected else "❌ DISCONNECTED"
        
        # Find next scheduled trade
        next_trade = scheduler.get_next_trade() if scheduler else None
        next_trade_str = f"{next_trade['day']} {next_trade['time_et']} ET - {next_trade['name']}" if next_trade else "None"
        
        # Calculate uptime
        uptime_seconds = int(time.time() - start_time)
        uptime_hours = uptime_seconds // 3600
        uptime_minutes = (uptime_seconds % 3600) // 60
        
        log_message(f"Connection: {connection_status}")
        log_message(f"Next Trade: {next_trade_str}")
        log_message(f"Market Hours: {'Yes' if is_market_hours() else 'No'}")
        log_message(f"Uptime: {uptime_hours}h {uptime_minutes}m")
    
    connection_manager = None
    scheduler = None
    
    try:
        while True:
            if stop_event and stop_event.is_set():
                log_message("\nShutdown requested. Stopping trading system...")
                if connection_manager:
                    connection_manager.disconnect()
                return  # Exit immediately
                
            try:
                # Initialize connection manager if needed
                if not connection_manager:
                    connection_manager = ConnectionManager(client_id=99, check_interval=180, stop_event=stop_event)
                
                # Verify we have a valid connection before proceeding
                if not connection_manager.tws or not connection_manager.tws.isConnected():
                    log_message("\nFailed to establish connection. Cannot proceed without valid connection.")
                    update_status(connection_manager, scheduler)
                    log_message("Waiting 30 seconds before retry...")
                    time.sleep(30)
                    continue
                    
                # Initialize scheduler if needed
                if not scheduler:
                    scheduler = TradeScheduler()
                    
                    # Schedule all trades
                    # Schedule the first double calendar trade for 10:15 ET every Friday
                    scheduler.add_trade(
                        trade_name=DC_CONFIG.trade_name,
                        time_et="10:15",
                        trade_func=lambda: execute_double_calendar(connection_manager)
                    )
                    
                    # Schedule the second double calendar trade for 11:55 ET every Friday
                    scheduler.add_trade(
                        trade_name=DC_CONFIG_2.trade_name,
                        time_et="11:55",
                        trade_func=lambda: execute_dc_config_2(connection_manager)
                    )
                    
                    # Schedule the third double calendar trade for 13:00 ET every Friday
                    scheduler.add_trade(
                        trade_name=DC_CONFIG_3.trade_name,
                        time_et="13:00",
                        trade_func=lambda: execute_dc_config_3(connection_manager)
                    )
                    
                    # Schedule the fourth double calendar trade for 14:10 ET every Friday
                    scheduler.add_trade(
                        trade_name=DC_CONFIG_4.trade_name,
                        time_et="14:10",
                        trade_func=lambda: execute_dc_config_4(connection_manager)
                    )
                    
                    # Schedule the fifth double calendar trade for 12:00 ET every Monday
                    scheduler.add_trade(
                        trade_name=DC_CONFIG_5.trade_name,  # Will generate "DC_3D_77D_1217_0"
                        time_et="12:00",
                        trade_func=lambda: execute_dc_config_5(connection_manager),
                        day="Monday"
                    )
                    
                    # Schedule the sixth double calendar trade for 13:30 ET every Monday
                    scheduler.add_trade(
                        trade_name=DC_CONFIG_6.trade_name,  # Will generate "DC_1D_44D_2525_0"
                        time_et="13:30",
                        trade_func=lambda: execute_dc_config_6(connection_manager),
                        day="Monday"
                    )
                    
                    scheduler.list_trades()
                    log_message("\n⚡ Trade scheduler is running...")
                    log_message("Monitoring connection and waiting for scheduled trades...")
                
                # Main operation loop
                while True:
                    if stop_event and stop_event.is_set():
                        log_message("\nShutdown requested. Stopping trading system...")
                        connection_manager.disconnect()
                        return  # Exit immediately
                        
                    current_time = time.time()
                    
                    # Update status every 5 seconds
                    if current_time - last_status_check >= 5:
                        update_status(connection_manager, scheduler)
                        last_status_check = current_time
                    
                    # Connection check
                    if current_time - last_check >= connection_manager.check_interval:
                        if not connection_manager.check_connection():
                            consecutive_failures += 1
                            log_message(f"Connection check failed ({consecutive_failures}/{max_consecutive_failures})")
                            update_status(connection_manager, scheduler)
                            
                            if consecutive_failures >= max_consecutive_failures:
                                log_message("Too many consecutive connection failures. Restarting entire system...")
                                connection_manager.disconnect()
                                connection_manager = None  # Force reconnection
                                break
                            
                            log_message("Waiting 30 seconds before retry...")
                            time.sleep(30)
                            continue
                        else:
                            consecutive_failures = 0
                        last_check = current_time
                    
                    if is_market_hours():
                        if not connection_manager.tws or not connection_manager.tws.isConnected():
                            log_message("\nConnection lost, attempting to reconnect...")
                            update_status(connection_manager, scheduler)
                            if not connection_manager.connect_with_retry():
                                log_message("Failed to reconnect. Restarting entire system...")
                                connection_manager = None  # Force reconnection
                                break
                            continue
                        scheduler.run()
                    
                    time.sleep(0.1 if is_market_hours() else 1.0)
                    
            except Exception as e:
                log_message(f"\nUnexpected error: {str(e)}")
                log_message("Restarting entire system...")
                if connection_manager:
                    connection_manager.disconnect()
                    connection_manager = None  # Force reconnection
                time.sleep(30)
                continue
                
    finally:
        # Ensure clean shutdown
        if connection_manager:
            try:
                connection_manager.disconnect()
            except:
                pass
        log_message("\nTrading system shutdown complete.")

if __name__ == "__main__":
    # Check if we want to view recent trades
    if len(sys.argv) > 1 and sys.argv[1] == "--show-trades":
        check_recent_trades()
    else:
        main() 