from pyetrade import ETradeOAuth
from pyetrade.market import ETradeMarket
import datetime
import webbrowser

# Sandbox credentials
consumer_key = "f1bd5f2dfaf8c2174ee761073aff60e5"
consumer_secret = "dccaa68641577f97e333ce12bac157c1a329c1a9fd96ac4a9b9440e7f75580a1"

def authenticate():
    """Handle E*TRADE OAuth authentication"""
    oauth = ETradeOAuth(consumer_key, consumer_secret)
    
    # Get request token and URL
    verify_url = oauth.get_request_token()
    
    # Open browser for user to authenticate
    print(f"\nPlease authorize the application:")
    print(verify_url)
    webbrowser.open(verify_url)
    
    # Get verification code from user
    verification_code = input("\nEnter the verification code: ")
    
    # Get access tokens
    tokens = oauth.get_access_token(verification_code)
    return tokens

def test_historical_access(tokens):
    """Test historical options data access"""
    try:
        # Initialize API with tokens
        market = ETradeMarket(consumer_key, consumer_secret, tokens['oauth_token'],
                            tokens['oauth_token_secret'], dev=True)
        
        # Try to get data from 30 days ago
        date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
        
        print(f"\nRequesting option chain for SPX, date: {date}")
        chain = market.get_option_chains(
            symbol="SPX",
            expiry=date,
            strike_price_near=4500
        )
        
        print("\nHistorical data available!")
        print(chain)
        
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    print("Starting E*TRADE API test...")
    tokens = authenticate()
    test_historical_access(tokens)