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
        
        # For calls: Start ~50 points OTM for 0.15 delta
        # Round to nearest 5 points for SPX strikes
        call_strike = round((spx_price + 50) / 5) * 5
        
        # Keep track of the best option we've found
        best_delta_diff = float('inf')
        best_option = None
        
        # Keep track of strikes we've tried to avoid loops
        tried_strikes = set()
        
        # Track high and low bounds to help with binary search
        high_strike = None  # Strike that gave delta < 0.15
        low_strike = None   # Strike that gave delta > 0.15
        
        print("\nSearching for 0.15 delta call option...")
        
        while True:
            if call_strike in tried_strikes:
                # We've tried this strike before, we must be in a loop
                # Take the best option we've found
                break
                
            print(f"\nTrying strike {call_strike}...")
            tried_strikes.add(call_strike)
            
            target_calls = tws.request_option_chain(expiry, "C", call_strike, call_strike, target_delta=0.15)
            
            if not target_calls:
                print("No options returned from request")
                return
                
            current_delta = target_calls[0].delta
            current_diff = abs(current_delta - 0.15)
            print(f"Found option with delta: {current_delta:.4f} (diff: {current_diff:.4f})")
            
            # Keep track of the best option we've found
            if current_diff < best_delta_diff:
                best_delta_diff = current_diff
                best_option = target_calls[0]
                print(f"New best option found! Delta: {current_delta:.4f}")
            
            # If we're within 0.01 of target, we'll take it
            if 0.14 <= current_delta <= 0.16:
                print(f"\nFound excellent option!")
                print(f"Strike: {target_calls[0].contract.strike}")
                print(f"Delta: {current_delta:.4f}")
                print(f"IV: {target_calls[0].implied_vol:.4f}")
                print(f"Symbol: {target_calls[0].contract.localSymbol}")
                break
                
            # Update our bounds and use them to make a better guess
            if current_delta > 0.15:
                low_strike = call_strike
                if high_strike is None:
                    # First time above target, move up by 25
                    adjustment = 25
                else:
                    # We have bounds, take the middle
                    adjustment = (high_strike - call_strike) // 2
            else:
                high_strike = call_strike
                if low_strike is None:
                    # First time below target, move down by 25
                    adjustment = -25
                else:
                    # We have bounds, take the middle
                    adjustment = (low_strike - call_strike) // 2
            
            # Ensure adjustment is at least 5 points
            if abs(adjustment) < 5:
                adjustment = 5 if adjustment > 0 else -5
                
            # Round to nearest 5
            call_strike = round((call_strike + adjustment) / 5) * 5
            print(f"Adjusting strike by {adjustment} to {call_strike}")
            
            time.sleep(1)  # Add delay between attempts
        
        # If we didn't find an excellent option, use the best one we found
        if best_option and (not 0.14 <= best_option.delta <= 0.16):
            print(f"\nUsing best option found:")
            print(f"Strike: {best_option.contract.strike}")
            print(f"Delta: {best_option.delta:.4f}")
            print(f"IV: {best_option.implied_vol:.4f}")
            print(f"Symbol: {best_option.contract.localSymbol}")
            
        return
        
    finally:
        print("\nDisconnecting from TWS...")
        tws.disconnect()

if __name__ == "__main__":
    main() 