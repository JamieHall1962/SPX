from tws_connector import TWSConnector
from order_manager import OrderManager, OrderType
import time
from datetime import datetime

def find_strike_by_delta(options, target_delta):
    """Find the strike price closest to target delta"""
    closest = None
    min_diff = float('inf')
    for opt in options:
        if opt.delta is None:
            continue
        # For puts, delta is negative
        delta = abs(opt.delta)
        diff = abs(delta - abs(target_delta))
        if diff < min_diff:
            min_diff = diff
            closest = opt
    return closest.strike if closest else None

def main():
    # Connect to TWS
    tws = TWSConnector(host='127.0.0.1', port=7496, client_id=0)
    tws.connect()
    order_manager = OrderManager(tws)
    
    # Wait for connection and market data
    time.sleep(2)
    
    # Request SPX price
    tws.request_spx_data()
    
    # Wait for price data
    spx_price = None
    timeout = time.time() + 5  # 5 second timeout
    while spx_price is None and time.time() < timeout:
        try:
            msg = tws.data_queue.get_nowait()
            if msg[0] == 'price' and msg[2] == 4:  # Last price
                spx_price = msg[3]
            elif msg[0] == 'historical':
                spx_price = msg[2].close
        except:
            time.sleep(0.1)
    
    if spx_price is None:
        print("Error: Could not get SPX price")
        tws.disconnect()
        return
        
    print(f"\nCurrent SPX price: {spx_price}")
    
    # Today's expiry
    today = datetime.now()
    expiry = today.strftime('%Y%m%d')
    
    # Get strikes within ±10% of current price
    strike_range = spx_price * 0.10
    min_strike = spx_price - strike_range
    max_strike = spx_price + strike_range
    
    # Request option chains
    puts = tws.request_option_chain(
        expiry=expiry,
        right="P",
        min_strike=min_strike,
        max_strike=max_strike
    )
    calls = tws.request_option_chain(
        expiry=expiry,
        right="C",
        min_strike=min_strike,
        max_strike=max_strike
    )
    
    time.sleep(2)  # Wait for option data
    
    # Find strikes at ~15 delta
    put_short_strike = find_strike_by_delta(puts, -0.15)
    call_short_strike = find_strike_by_delta(calls, 0.15)
    
    if not put_short_strike or not call_short_strike:
        print("Error: Could not find suitable strikes")
        tws.disconnect()
        return
        
    # Create Iron Condor legs
    put_long = tws.get_spx_option_contract("P", put_short_strike - 30, expiry)
    put_short = tws.get_spx_option_contract("P", put_short_strike, expiry)
    call_short = tws.get_spx_option_contract("C", call_short_strike, expiry)
    call_long = tws.get_spx_option_contract("C", call_short_strike + 30, expiry)
    
    # Create BAG order
    order_id = order_manager.create_bag_order(
        legs=[
            (put_long, 1),    # Buy put wing
            (put_short, -1),  # Sell put
            (call_short, -1), # Sell call
            (call_long, 1)    # Buy call wing
        ],
        order_type=OrderType.LIMIT,
        limit_price=1.00  # Set a limit price that won't get filled
    )
    
    # Submit the order
    print(f"\nSubmitting Iron Condor order: {order_id}")
    order_manager.submit_order(order_id)
    
    # Keep the script running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDisconnecting...")
        tws.disconnect()

if __name__ == "__main__":
    main() 