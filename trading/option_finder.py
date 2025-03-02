from datetime import datetime, timedelta, time
import pytz
import time
from typing import Optional
import queue
from connection.tws_manager import ConnectionManager, OptionPosition
from utils.date_utils import get_next_futures_month

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

def is_market_hours() -> bool:
    """Check if current time is during market hours (9:30 AM - 4:15 PM ET)"""
    et_timezone = pytz.timezone('US/Eastern')
    current_time = datetime.now(et_timezone).time()
    
    market_open = time(9, 30)  # 9:30 AM ET
    market_close = time(16, 15)  # 4:15 PM ET
    
    # Check if current time is between market open and close
    return market_open <= current_time <= market_close

def find_target_delta_option(tws, expiry: str, right: str, price: float, target_delta: float = None) -> Optional[OptionPosition]:
    """Find an option contract with target delta"""
    print(f"\nLooking for {right} option with target delta/premium: {target_delta}")
    
    # Round price to nearest 5
    initial_strike = round(price / 5) * 5
    
    print("Initial parameters:")
    print(f"Expiry: {expiry}")
    print(f"Right: {right}")
    print(f"Initial Strike: {initial_strike}")
    print(f"Target Delta: {target_delta}")
    
    if target_delta:
        print("Searching by delta")
    else:
        print("Using exact strike")

    print(f"\nRequesting option chain for:")
    print(f"SPX {right} {initial_strike} {expiry}")
    
    # Request option chain
    chain = tws.request_option_chain("SPX", expiry, right, initial_strike)
    
    if not chain:
        print("Failed to get option chain")
        return None
        
    # Get initial option's delta or premium
    if target_delta:
        # Request bid/ask for accurate pricing
        req_id = tws.get_next_req_id()
        tws.reqMktData(req_id, chain[0].contract, "100,101", False, False, [])  # Request bid/ask
        
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
        current_value = chain[0].delta if chain[0].delta is not None else 0
        print(f"Initial {right} option delta: {current_value:.3f}")
    
    # Initialize search variables
    best_option = chain[0]
    best_diff = abs(current_value - target_delta)
    
    # Determine search direction
    if target_delta:
        # For premium: higher strike = lower premium
        search_up = current_value > target_delta
    else:
        # For delta: 
        # For puts: if delta is too low, move UP to get higher delta
        # For calls: if delta is too high, move UP to get lower delta
        search_up = (right == "P" and current_value < target_delta) or (right == "C" and current_value > target_delta)
    
    print(f"\nSearch direction: {'UP' if search_up else 'DOWN'} from strike {best_option.contract.strike}")
    print(f"Current {('premium' if target_delta else 'delta'):<8}: {current_value:.3f}, Target: {target_delta:.3f}")
    print(f"Moving strike {'up' if search_up else 'down'} in 5-point increments")
    
    max_attempts = 20  # Prevent infinite loops
    attempts = 0
    
    while attempts < max_attempts:
        attempts += 1
        
        # Calculate next strike
        next_strike = best_option.contract.strike + (5 if search_up else -5)
        print(f"\nAttempt {attempts}/{max_attempts}:")
        print(f"Checking strike: {next_strike}")
        
        # Get option chain for next strike
        options = tws.request_option_chain(expiry, right, next_strike, next_strike)
        if not options:
            print(f"No options found at strike {next_strike}")
            break
            
        # Get new option's delta or premium
        if target_delta:
            current_value = tws.get_option_price(options[0].contract)
            print(f"Strike {next_strike}: premium = {current_value:.2f} (target: {target_delta:.2f})")
        else:
            current_value = options[0].delta if options[0].delta is not None else 0
            print(f"Strike {next_strike}: delta = {current_value:.3f} (target: {target_delta:.3f})")
            
        # Check if this option is better
        current_diff = abs(current_value - target_delta)
        previous_diff = abs(best_option.delta - target_delta) if not target_delta else abs(best_option.market_price - target_delta)
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
        if not target_delta:
            # For puts: if delta is still too low, keep moving UP
            # For calls: if delta is still too high, keep moving UP
            search_up = (right == "P" and current_value < target_delta) or (right == "C" and current_value > target_delta)
    
    if best_option:
        if target_delta:
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