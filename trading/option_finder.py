from datetime import datetime, timedelta
import pytz
import time
from typing import Optional
import queue
from connection.tws_manager import TWSConnector, OptionPosition

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
    """Find an option with a target delta using binary search"""
    print(f"\nLooking for {right} option with target delta/premium: {target_delta}")
    print(f"Initial parameters:")
    print(f"Expiry: {expiry}")
    print(f"Right: {right}")
    print(f"Initial Strike: {initial_strike}")
    print(f"Target Delta: {target_delta}")
    
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
    print(f"\nRequesting option chain for:")
    print(f"SPX {right} {initial_strike} {expiry}")
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
    
    # Determine search direction
    if searching_by_premium:
        # For premium: higher strike = lower premium
        search_up = current_value > target_delta
    else:
        # For delta: 
        # For puts: if delta is too low, move UP to get higher delta
        # For calls: if delta is too high, move UP to get lower delta
        search_up = (right == "P" and current_value < target_delta) or (right == "C" and current_value > target_delta)
    
    print(f"\nSearch direction: {'UP' if search_up else 'DOWN'} from strike {best_option.contract.strike}")
    print(f"Current {search_type}: {current_value:.3f}, Target: {target_delta:.3f}")
    print(f"Moving strike {'up' if search_up else 'down'} in {strike_increment}-point increments")
    
    max_attempts = 20  # Prevent infinite loops
    attempts = 0
    
    while attempts < max_attempts:
        attempts += 1
        
        # Calculate next strike
        next_strike = best_option.contract.strike + (strike_increment if search_up else -strike_increment)
        print(f"\nAttempt {attempts}/{max_attempts}:")
        print(f"Checking strike: {next_strike}")
        
        # Get option chain for next strike
        options = tws.request_option_chain(expiry, right, next_strike, next_strike)
        if not options:
            print(f"No options found at strike {next_strike}")
            break
            
        # Get new option's delta or premium
        if searching_by_premium:
            current_value = tws.get_option_price(options[0].contract)
            print(f"Strike {next_strike}: premium = {current_value:.2f} (target: {target_delta:.2f})")
        else:
            current_value = options[0].delta if options[0].delta is not None else 0
            print(f"Strike {next_strike}: delta = {current_value:.3f} (target: {target_delta:.3f})")
            
        # Check if this option is better
        current_diff = abs(current_value - target_delta)
        previous_diff = abs(best_option.delta - target_delta) if not searching_by_premium else abs(best_option.market_price - target_delta)
        print(f"Current difference: {current_diff:.3f}, Previous best: {previous_diff:.3f}")
        
        if current_diff < previous_diff:
            print(f"Found better option - updating best")
            best_diff = current_diff
            best_option = options[0]
            
            # If we're very close to target, stop searching
            if current_diff < 0.02:  # Within 0.02 of target
                print(f"Within 0.02 of target - stopping search")
                break
        elif current_diff > previous_diff * 1.5:  # If getting significantly worse
            print(f"Getting significantly worse - stopping search")
            break
            
        # Update search direction based on new value
        if not searching_by_premium:
            # For puts: if delta is still too low, keep moving UP
            # For calls: if delta is still too high, keep moving UP
            search_up = (right == "P" and current_value < target_delta) or (right == "C" and current_value > target_delta)
    
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
                best_option.market_price = round(((bid + ask) / 2) * 20) / 20  # Round to nearest 0.05
                print(f"\nBest option found:")
                print(f"Strike: {best_option.contract.strike}")
                print(f"Premium: {best_option.market_price:.2f} (bid: {bid:.2f}, ask: {ask:.2f})")
            else:
                print("\nWarning: Could not get final bid/ask prices")
        else:
            print(f"\nBest option found:")
            print(f"Strike: {best_option.contract.strike}")
            print(f"Delta: {best_option.delta:.3f}")
    
    return best_option