from tws_connector import TWSConnector
import time
from datetime import datetime, timedelta
import pytz
from trade_scheduler import TradeScheduler

def is_market_hours():
    """Check if it's currently market hours (9:30 AM - 4:15 PM ET, Mon-Fri)"""
    et_time = datetime.now(pytz.timezone('US/Eastern'))
    
    # Check if it's a weekday
    if et_time.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    
    # Convert time to decimal hours for easier comparison
    hour_dec = et_time.hour + et_time.minute/60
    
    # Market hours are 9:30 AM - 4:15 PM ET
    return 9.5 <= hour_dec <= 16.25

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
                quantity=1,
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
                    quantity=1,
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
                        quantity=1,
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

def main():
    """Main function that sets up the scheduler"""
    scheduler = TradeScheduler()
    
    # Schedule the iron condor trade for 15:02 ET
    scheduler.add_trade(
        trade_name="SPX Iron Condor",
        time_et="15:02",
        trade_func=execute_iron_condor
    )
    
    # List all scheduled trades
    scheduler.list_trades()
    
    # Run the scheduler
    try:
        scheduler.run()
    except KeyboardInterrupt:
        print("\nShutting down scheduler...")

if __name__ == "__main__":
    main() 