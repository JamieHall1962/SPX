from tws_connector import TWSConnector
import time
from datetime import datetime, timedelta
import pytz
import queue
from ibapi.contract import Contract

def get_today_expiry():
    """Get tomorrow's date for 1DTE options"""
    et_tz = pytz.timezone('US/Eastern')
    now = datetime.now(et_tz)
    tomorrow = now + timedelta(days=1)
    return tomorrow.strftime('%Y%m%d')

def main():
    # Initialize TWS connection
    tws = TWSConnector(client_id=99)
    try:
        print("Connecting to TWS...")
        tws.connect()
        
        def try_get_option(strike, option_type, attempt=1, max_attempts=3):
            """Helper function to request option data with retries"""
            print(f"Requesting {option_type} option at strike {strike}...")
            
            # Get expiry for 1DTE
            expiry = get_today_expiry()
            
            # Request option chain around the strike
            options = tws.request_option_chain(
                expiry=expiry,
                right=option_type,
                min_strike=strike - 5,  # Look within 5 points
                max_strike=strike + 5,
                target_delta=0.15 if option_type == "C" else -0.15
            )
            
            # Find the closest strike
            closest_option = None
            min_diff = float('inf')
            for opt in options:
                if opt.contract.strike == strike:
                    closest_option = opt
                    break
                diff = abs(opt.contract.strike - strike)
                if diff < min_diff:
                    min_diff = diff
                    closest_option = opt
            
            if not closest_option:
                if attempt < max_attempts:
                    print(f"Contract not found, retrying {option_type} option request...")
                    time.sleep(1)
                    return try_get_option(strike, option_type, attempt + 1, max_attempts)
                return None
            
            # Use the qualified contract from the option chain
            contract = closest_option.contract
            contract.exchange = "CBOE"
            
            # Request market data
            req_id = tws.get_next_req_id()
            tws.reqMktData(req_id, contract, "106,165,221,232", False, False, [])
            
            # Wait for Greeks data
            got_data = False
            start_time = time.time()
            result = None
            
            while time.time() - start_time < 2:
                try:
                    msg = tws.data_queue.get(timeout=0.1)
                    if msg[0] == 'option_computation':
                        _, msg_req_id, tick_type, impl_vol, delta, gamma, vega, theta, opt_price = msg
                        
                        if msg_req_id == req_id and delta != -2 and delta != 0:
                            got_data = True
                            result = {
                                'strike': strike,
                                'delta': delta,
                                'iv': impl_vol if impl_vol > 0 else None,
                                'symbol': contract.localSymbol
                            }
                            break
                except queue.Empty:
                    continue
            
            # Cancel market data request
            tws.cancelMktData(req_id)
            
            if got_data:
                return result
            elif attempt < max_attempts:
                print(f"Attempt {attempt} failed, retrying {option_type} option request...")
                time.sleep(1)
                return try_get_option(strike, option_type, attempt + 1, max_attempts)
            return None

        def find_option_with_target_delta(start_strike, option_type, max_tries=5):
            """Find an option with delta close to 0.15 (or -0.15 for puts)"""
            current_strike = start_strike
            tries = 0
            last_result = None
            
            while tries < max_tries:
                result = try_get_option(current_strike, option_type, max_attempts=4)
                if result:
                    delta = abs(result['delta']) if option_type == "P" else result['delta']
                    if 0.10 <= delta <= 0.20:
                        return result
                    
                    # Store last valid result
                    last_result = result
                    
                    # Adjust strike based on delta
                    if option_type == "C":
                        adjustment = 5 if delta < 0.15 else -5
                    else:  # Put option
                        adjustment = -5 if delta < 0.15 else 5
                    
                    current_strike = round((current_strike + adjustment) / 5) * 5
                    print(f"{option_type} delta {delta:.4f} not close enough to 0.15, trying strike {current_strike}")
                else:
                    # If request failed, try a different strike
                    current_strike += 5 if option_type == "C" else -5
                    print(f"Failed to get data, trying strike {current_strike}")
                
                tries += 1
                time.sleep(1)  # Wait between attempts
            
            # If we couldn't find an ideal option, return the last valid one we found
            return last_result

        # Get SPX price and wait for data
        tws.request_spx_data()
        timeout = time.time() + 3
        spx_price = None
        
        # Wait for either real-time or historical data
        while time.time() < timeout:
            try:
                msg = tws.data_queue.get(timeout=0.1)
                if msg[0] == 'price' and msg[2] == 4:  # Last price
                    spx_price = msg[3]
                    break
                elif msg[0] == 'historical':  # Historical data
                    spx_price = msg[2].close
                    break
            except queue.Empty:
                continue
        
        if spx_price is None:
            print("Failed to get SPX price")
            return
            
        print(f"\nSPX Price: {spx_price:.2f}\n")
        time.sleep(1)  # Give TWS time before first request
            
        # Get expiry for 1DTE
        expiry = get_today_expiry()
        print(f"Using expiry: {expiry}")
        
        # Find call option - start ~20 points OTM
        print("\nFinding 0.15 delta call...")
        call_strike = round((spx_price + 20) / 5) * 5
        call_result = find_option_with_target_delta(call_strike, "C")
        
        time.sleep(1.5)  # Longer wait between call and put
        
        # Find put option - start ~20 points OTM
        print("\nFinding 0.15 delta put...")
        put_strike = round((spx_price - 20) / 5) * 5
        put_result = find_option_with_target_delta(put_strike, "P")
        
        # Cancel SPX data
        tws.cancelMktData(1)
        
        # Print final summary
        print("\n" + "="*50)
        print("🎯 FINAL RESULTS")
        print("="*50)
        print(f"SPX Price: {spx_price:.2f}")
        print("-"*50)
        
        if call_result and 0.10 <= call_result['delta'] <= 0.20:
            print("\n📞 CALL OPTION:")
            print(f"   Strike: {call_result['strike']}")
            print(f"   Delta: {call_result['delta']:.4f}")
            print(f"   IV: {call_result['iv']:.4f if call_result['iv'] is not None else 'N/A'}")
            print(f"   Symbol: {call_result['symbol']}")
        else:
            print("\n❌ No suitable call option found")
            
        if put_result and 0.10 <= abs(put_result['delta']) <= 0.20:
            print("\n📉 PUT OPTION:")
            print(f"   Strike: {put_result['strike']}")
            print(f"   Delta: {put_result['delta']:.4f}")
            print(f"   IV: {put_result['iv']:.4f if put_result['iv'] is not None else 'N/A'}")
            print(f"   Symbol: {put_result['symbol']}")
        else:
            print("\n❌ No suitable put option found")
            
        print("\n" + "="*50)
        
    finally:
        print("\nDisconnecting from TWS...")
        tws.disconnect()

if __name__ == "__main__":
    main() 