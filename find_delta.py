from tws_connector import TWSConnector
import time
from datetime import datetime, timedelta
import pytz

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

def main():
    # Initialize TWS connection
    tws = TWSConnector(client_id=99)
    try:
        print("Connecting to TWS...")
        tws.connect()
        time.sleep(1)  # Give TWS time to fully establish connection
        
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
        
        # Find 0.15 delta call
        call_strike = round((spx_price + 50) / 5) * 5  # Start ~50 points OTM
        call_option = find_target_delta_option(tws, expiry, "C", call_strike)
        
        # Find 0.15 delta put
        put_strike = round((spx_price - 50) / 5) * 5  # Start ~50 points OTM
        put_option = find_target_delta_option(tws, expiry, "P", put_strike)
        
        # Print final summary
        print("\n" + "="*50)
        print("🎯 FINAL RESULTS")
        print("="*50)
        print(f"SPX Price: {spx_price:.2f}")
        print(f"Expiry: {expiry} (1DTE)")
        print("-"*50)
        
        if call_option:
            print("\n📞 CALL OPTION:")
            print(f"   Strike: {call_option.contract.strike}")
            print(f"   Delta: {call_option.delta:.4f}")
            print(f"   IV: {call_option.implied_vol:.4f}")
            print(f"   Symbol: {call_option.contract.localSymbol}")
        else:
            print("\n❌ No suitable call option found")
            
        if put_option:
            print("\n📉 PUT OPTION:")
            print(f"   Strike: {put_option.contract.strike}")
            print(f"   Delta: {put_option.delta:.4f}")
            print(f"   IV: {put_option.implied_vol:.4f}")
            print(f"   Symbol: {put_option.contract.localSymbol}")
        else:
            print("\n❌ No suitable put option found")
            
        print("\n" + "="*50)
        
    finally:
        print("\nDisconnecting from TWS...")
        tws.disconnect()

if __name__ == "__main__":
    main() 