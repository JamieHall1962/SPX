from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from threading import Thread, Lock
import time
import datetime
import pytz

class TestWrapper(EWrapper):
    def __init__(self):
        super().__init__()
        self.spx_price = None
        self.es_price = None

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        print(f'Error {errorCode}: {errorString}')

    def tickPrice(self, reqId, tickType, price, attrib):
        if tickType in [1, 2, 4, 6, 9, 14]:  # Bid, Ask, Last, High, Low, Open
            if reqId == 1:
                print(f'SPX Price: {price}')
                self.spx_price = price
            elif reqId == 2:
                print(f'ES Price: {price}')
                self.es_price = price

class TestClient(EClient):
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)

class TestApp:
    def __init__(self):
        self.wrapper = TestWrapper()
        self.client = TestClient(self.wrapper)
        self.next_valid_id = None

    def connect(self):
        print("Connecting to TWS...")
        self.client.connect("127.0.0.1", 7496, 1)
        
        # Start the client thread
        thread = Thread(target=self.client.run)
        thread.start()
        
        # Wait for connection
        time.sleep(2)
        
        if self.client.isConnected():
            print("Connected to TWS")
            self.request_market_data()
        else:
            print("Failed to connect")
            return
        
        # Keep the main thread running
        while True:
            time.sleep(1)

    def request_market_data(self):
        # SPX Index
        spx = Contract()
        spx.symbol = "SPX"
        spx.secType = "IND"
        spx.exchange = "CBOE"
        spx.currency = "USD"

        # ES Future
        es = Contract()
        es.symbol = "ES"
        es.secType = "FUT"
        es.exchange = "CME"
        es.currency = "USD"
        es.lastTradeDateOrContractMonth = "202503"  # March 2025

        print("Requesting market data...")
        self.client.reqMktData(1, spx, "", False, False, [])
        self.client.reqMktData(2, es, "", False, False, [])

if __name__ == "__main__":
    app = TestApp()
    app.connect()
