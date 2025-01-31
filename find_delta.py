from tws_connector import TWSConnector
import time
from datetime import datetime, timedelta
import pytz
from trade_scheduler import TradeScheduler
from trade_config import TradeConfig, DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3, DC_CONFIG_4

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

def find_target_delta_option(tws, expiry: str, right: str, initial_strike: float, target_delta: float = 0.15):
    """Search for an option with target delta using binary search"""
    # Keep track of the best option we've found
    best_delta_diff = float('inf')
    best_option = None
    
    # Keep track of strikes we've tried to avoid loops
    tried_strikes = set()
    
    # Track high and low bounds to help with binary search
    high_strike = None  # Strike that gave delta < target
    low_strike = None   # Strike that gave delta > target
    
    current_strike = initial_strike
    target_delta = target_delta if right == "C" else -target_delta  # Negative for puts
    
    print(f"\nSearching for {abs(target_delta):.2f} delta {right}...")
    
    while True:
        if current_strike in tried_strikes:
            break
            
        print(f"\nTrying strike {current_strike}...")
        tried_strikes.add(current_strike)
        
        options = tws.request_option_chain(expiry, right, current_strike, current_strike, target_delta=abs(target_delta))
        
        if not options:
            print("No options returned from request")
            return None
            
        current_delta = options[0].delta
        current_diff = abs(current_delta - target_delta)
        print(f"Found option with delta: {current_delta:.4f} (diff: {current_diff:.4f})")
        
        # Keep track of the best option we've found
        if current_diff < best_delta_diff:
            best_delta_diff = current_diff
            best_option = options[0]
            print(f"New best option found! Delta: {current_delta:.4f}")
        
        # If we're within 0.01 of target, we'll take it
        if abs(current_delta - target_delta) <= 0.01:
            print(f"\nFound excellent option!")
            print(f"Strike: {options[0].contract.strike}")
            print(f"Delta: {current_delta:.4f}")
            print(f"IV: {options[0].implied_vol:.4f}")
            print(f"Symbol: {options[0].contract.localSymbol}")
            return options[0]
            
        # Update our bounds and use them to make a better guess
        if current_delta > target_delta:
            low_strike = current_strike
            if high_strike is None:
                # First time above target
                if right == "C":
                    # For calls: delta too high, move strike up
                    adjustment = 25
                else:
                    # For puts: delta too high (e.g. -0.10), move strike up
                    adjustment = 25
            else:
                adjustment = (high_strike - current_strike) // 2
        else:
            high_strike = current_strike
            if low_strike is None:
                # First time below target
                if right == "C":
                    # For calls: delta too low, move strike down
                    adjustment = -25
                else:
                    # For puts: delta too low (e.g. -0.20), move strike down
                    adjustment = -25
            else:
                adjustment = (low_strike - current_strike) // 2
        
        # Ensure adjustment is at least 5 points
        if abs(adjustment) < 5:
            adjustment = 5 if adjustment > 0 else -5
            
        # Round to nearest 5
        current_strike = round((current_strike + adjustment) / 5) * 5
        print(f"Adjusting strike by {adjustment} to {current_strike}")
        
        time.sleep(1)  # Add delay between attempts
    
    # If we didn't find an excellent option, use the best one we found
    if best_option:
        print(f"\nUsing best option found:")
        print(f"Strike: {best_option.contract.strike}")
        print(f"Delta: {best_option.delta:.4f}")
        print(f"IV: {best_option.implied_vol:.4f}")
        print(f"Symbol: {best_option.contract.localSymbol}")
        
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
    def __init__(self, client_id=99, check_interval=180):  # Check every 3 minutes
        self.client_id = client_id
        self.check_interval = check_interval
        self.tws = None
        self.last_check = 0
        self.connect()
    
    def connect(self):
        """Establish connection to TWS"""
        if self.tws is None:
            self.tws = TWSConnector(client_id=self.client_id)
        
        if not self.tws.is_connected():
            print("\nConnecting to TWS...")
            try:
                self.tws.connect()
                time.sleep(1)  # Wait for connection to stabilize
                print("Successfully connected to TWS")
            except Exception as e:
                print(f"Failed to connect to TWS: {str(e)}")
                return False
        return True
    
    def check_connection(self):
        """Check connection status and reconnect if needed"""
        current_time = time.time()
        
        # Only check every check_interval seconds
        if current_time - self.last_check < self.check_interval:
            return True
            
        self.last_check = current_time
        
        if not self.tws or not self.tws.is_connected():
            print("\nConnection lost, attempting to reconnect...")
            return self.connect()
        
        return True
    
    def get_tws(self):
        """Get the TWS connection, checking/reconnecting if needed"""
        if self.check_connection():
            return self.tws
        return None
    
    def disconnect(self):
        """Gracefully disconnect from TWS"""
        if self.tws and self.tws.is_connected():
            print("\nDisconnecting from TWS...")
            self.tws.disconnect()
            self.tws = None

def execute_double_calendar(connection_manager: ConnectionManager, config: TradeConfig = DC_CONFIG):
    """Execute a double calendar trade strategy"""
    tws = connection_manager.get_tws()
    if not tws:
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
            print("Failed to get SPX price after all retries")
            return
            
        spx_price = tws.spx_price
        print(f"\nSPX Price: {spx_price:.2f}")
        
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
        
        # Submit the order
        order_id = tws.submit_double_calendar(
            short_put_contract=short_put.contract,
            long_put_contract=long_put.contract,
            short_call_contract=short_call.contract,
            long_call_contract=long_call.contract,
            quantity=config.quantity,
            total_debit=total_debit
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
        
        print("\n" + "="*50)
        
    finally:
        if tws is None:  # Only disconnect if we created the connection
            print("\nDisconnecting from TWS...")
            tws.disconnect()

def execute_dc_config_2(connection_manager):
    """Wrapper function to execute DC_CONFIG_2"""
    return execute_double_calendar(connection_manager, config=DC_CONFIG_2)

def execute_dc_config_3(connection_manager):
    """Wrapper function to execute DC_CONFIG_3"""
    return execute_double_calendar(connection_manager, config=DC_CONFIG_3)

def execute_dc_config_4(connection_manager):
    """Wrapper function to execute DC_CONFIG_4"""
    return execute_double_calendar(connection_manager, config=DC_CONFIG_4)

def main():
    """Main function that sets up the scheduler and connection manager"""
    connection_manager = ConnectionManager(client_id=99, check_interval=180)
    scheduler = TradeScheduler()
    
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
    
    # List all scheduled trades
    scheduler.list_trades()
    
    # Run the scheduler with connection monitoring
    try:
        while True:
            # Check connection status periodically
            if not connection_manager.check_connection():
                print("Unable to maintain TWS connection, retrying in 30 seconds...")
                time.sleep(30)
                continue
                
            scheduler.run(blocking=False)  # Non-blocking to allow connection checks
            time.sleep(1)  # Sleep to prevent CPU spinning
            
    except KeyboardInterrupt:
        print("\nShutting down scheduler...")
    finally:
        # Connection will be maintained until explicitly disconnected
        # This allows for future dashboard integration
        pass

if __name__ == "__main__":
    main() 