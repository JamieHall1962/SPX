from tws_connector import TWSConnector
import time
from datetime import datetime, timedelta
import pytz

def get_today_expiry():
    """Get today's expiry in the correct format"""
    today = datetime.now()
    # If it's after 4:15 PM ET, use tomorrow
    et_time = datetime.now(pytz.timezone('US/Eastern'))
    if et_time.hour > 16 or (et_time.hour == 16 and et_time.minute >= 15):
        today += timedelta(days=1)
    return today.strftime('%Y%m%d')

def main():
    # Initialize TWS connection
    tws = TWSConnector(client_id=99)
    try:
        print("Connecting to TWS...")
        tws.connect()
        
        # Get SPX price
        tws.request_spx_data()
        timeout = time.time() + 3
        while tws.spx_price is None and time.time() < timeout:
            time.sleep(0.1)
        
        if tws.spx_price is None:
            print("Failed to get SPX price")
            return
            
        spx_price = tws.spx_price
        print(f"SPX Price: {spx_price:.2f}")
            
        expiry = "20250128"
        
        # For calls: Start ~15 points OTM (closer to expected 0.15 delta)
        call_strike = round((spx_price + 15) / 5) * 5
        print(f"\nFinding 0.15 delta call starting near {call_strike}...")
        target_calls = tws.request_option_chain(expiry, "C", call_strike, 0, target_delta=0.15)
        time.sleep(0.5)  # Give TWS time to process
        call_result = None
        if target_calls:
            call_result = {
                'strike': target_calls[0].contract.strike,
                'delta': target_calls[0].delta,
                'iv': target_calls[0].implied_vol,
                'symbol': target_calls[0].contract.localSymbol
            }
            tws.cancelMktData(target_calls[0].contract.conId)
        
        time.sleep(0.5)
        
        # For puts: Start ~15 points OTM (closer to expected -0.15 delta)
        put_strike = round((spx_price - 15) / 5) * 5
        print(f"\nFinding 0.15 delta put starting near {put_strike}...")
        target_puts = tws.request_option_chain(expiry, "P", put_strike, 0, target_delta=0.15)
        time.sleep(0.5)  # Give TWS time to process
        put_result = None
        if target_puts:
            put_result = {
                'strike': target_puts[0].contract.strike,
                'delta': target_puts[0].delta,
                'iv': target_puts[0].implied_vol,
                'symbol': target_puts[0].contract.localSymbol
            }
            tws.cancelMktData(target_puts[0].contract.conId)
        
        # Verify we got reasonable results for calls
        if not call_result or call_result['delta'] < 0.10 or call_result['delta'] > 0.20:
            print("\nRetrying call with adjusted strike...")
            # If delta too low, move strike down, if too high move strike up
            adjustment = -10 if (call_result and call_result['delta'] < 0.15) else 10
            call_strike = round((spx_price + adjustment) / 5) * 5
            time.sleep(0.5)  # Give TWS time between requests
            target_calls = tws.request_option_chain(expiry, "C", call_strike, 0, target_delta=0.15)
            time.sleep(0.5)  # Give TWS time to process
            if target_calls:
                call_result = {
                    'strike': target_calls[0].contract.strike,
                    'delta': target_calls[0].delta,
                    'iv': target_calls[0].implied_vol,
                    'symbol': target_calls[0].contract.localSymbol
                }
                tws.cancelMktData(target_calls[0].contract.conId)
        
        # Verify we got reasonable results for puts
        if not put_result or abs(put_result['delta']) < 0.10 or abs(put_result['delta']) > 0.20:
            print("\nRetrying put with adjusted strike...")
            # If abs(delta) too low, move strike up, if too high move strike down
            adjustment = 10 if (put_result and abs(put_result['delta']) < 0.15) else -10
            put_strike = round((spx_price + adjustment) / 5) * 5
            time.sleep(0.5)  # Give TWS time between requests
            target_puts = tws.request_option_chain(expiry, "P", put_strike, 0, target_delta=0.15)
            time.sleep(0.5)  # Give TWS time to process
            if target_puts:
                put_result = {
                    'strike': target_puts[0].contract.strike,
                    'delta': target_puts[0].delta,
                    'iv': target_puts[0].implied_vol,
                    'symbol': target_puts[0].contract.localSymbol
                }
                tws.cancelMktData(target_puts[0].contract.conId)
        
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
            
        if put_result and -0.20 <= put_result['delta'] <= -0.10:
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