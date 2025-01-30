from tws_connector import TWSConnector
from order_manager import OrderManager, OrderType
import time
from datetime import datetime

def get_spx_price(tws):
    """Get the current SPX price from the data queue"""
    tws.request_spx_data()
    timeout = time.time() + 5  # 5 second timeout
    
    while time.time() < timeout:
        try:
            msg = tws.data_queue.get_nowait()
            if msg[0] == 'price' and msg[2] == 4:  # Last price
                return msg[3]
            elif msg[0] == 'historical':
                return msg[2].close
        except:
            time.sleep(0.1)
    
    return None

def main():
    # Connect to TWS
    tws = TWSConnector(host='127.0.0.1', port=7496, client_id=0)
    tws.connect()
    
    # Wait for connection
    time.sleep(2)
    
    # Get SPX price
    spx_price = get_spx_price(tws)
    if spx_price is None:
        print("Error: Could not get SPX price")
        tws.disconnect()
        return
        
    print(f"\nCurrent SPX price: {spx_price}")
    
    # Today's expiry
    today = datetime.now()
    expiry = today.strftime('%Y%m%d')
    
    # Get strikes within ±5% of current price
    strike_range = spx_price * 0.05
    min_strike = spx_price - strike_range
    max_strike = spx_price + strike_range
    
    print(f"\nSearching for calls between {min_strike:.0f} and {max_strike:.0f}")
    
    # Request call options
    calls = tws.request_option_chain(
        expiry=expiry,
        right="C",
        min_strike=min_strike,
        max_strike=max_strike
    )
    
    time.sleep(2)  # Wait for option data
    
    # Find the call with ~15 delta
    target_delta = 0.15
    closest_call = None
    min_diff = float('inf')
    
    for call in calls:
        if call.delta is None:
            continue
        diff = abs(call.delta - target_delta)
        if diff < min_diff:
            min_diff = diff
            closest_call = call
    
    if closest_call is None:
        print("Error: Could not find suitable call option")
        tws.disconnect()
        return
    
    print(f"\nFound call option:")
    print(f"Strike: {closest_call.contract.strike}")
    print(f"Delta: {closest_call.delta}")
    print(f"Implied Vol: {closest_call.implied_vol}")
    print(f"Local Symbol: {closest_call.contract.localSymbol}")
    
    # Keep the script running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDisconnecting...")
        tws.disconnect()

if __name__ == "__main__":
    main() 