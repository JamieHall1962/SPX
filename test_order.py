from tws_connector import TWSConnector
from order_manager import OrderManager, OrderType
import time

def main():
    # Connect to TWS
    tws = TWSConnector(host='127.0.0.1', port=7496, client_id=0)
    tws.connect()
    order_manager = OrderManager(tws)
    
    # Wait for connection
    time.sleep(2)
    
    # Create front month contract
    front_contract = tws.get_spx_option_contract(
        right="P",
        strike=4800,
        expiry="20250127"
    )
    front_contract.exchange = "CBOE"
    
    # Create back month contract
    back_contract = tws.get_spx_option_contract(
        right="P",
        strike=4800,
        expiry="20250203"
    )
    back_contract.exchange = "CBOE"
    
    # Create BAG order
    order_id = order_manager.create_bag_order(
        legs=[
            (front_contract, -1),  # Sell front month
            (back_contract, 1)     # Buy back month
        ],
        order_type=OrderType.LIMIT,
        limit_price=1.00  # Set a limit price that won't get filled
    )
    
    # Submit the order
    print(f"\nSubmitting calendar spread order: {order_id}")
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