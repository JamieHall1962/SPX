from tws_connector import TWSConnector
import time

def main():
    print("\nMake sure TWS (Trader Workstation) is:")
    print("1. Running")
    print("2. Logged in")
    print("3. API connections are enabled (File -> Global Configuration -> API -> Settings)")
    print("4. Socket port is set to 7496\n")
    
    # Connect to TWS
    print("Connecting to TWS...")
    tws = TWSConnector(host='127.0.0.1', port=7496, client_id=99)
    
    try:
        tws.connect()
        print("Successfully connected to TWS")
        
        # Request SPX data
        print("\nRequesting SPX data...")
        tws.request_spx_data()
        
        # Wait for and process messages
        timeout = time.time() + 5  # 5 second timeout
        while time.time() < timeout:
            try:
                msg = tws.data_queue.get_nowait()
                print(f"Received message: {msg}")
                if msg[0] == 'price' and msg[2] == 4:  # Last price
                    print(f"\nSPX price: {msg[3]}")
                    break
                elif msg[0] == 'historical':
                    print(f"\nSPX last close: {msg[2].close}")
                    break
            except:
                time.sleep(0.1)
    
    except ConnectionError as e:
        print("\nError: Could not connect to TWS.")
        print("Please check that TWS is running and properly configured.")
        print(f"Detailed error: {str(e)}")
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}")
    finally:
        print("\nDisconnecting...")
        if hasattr(tws, 'disconnect'):
            tws.disconnect()

if __name__ == "__main__":
    main() 