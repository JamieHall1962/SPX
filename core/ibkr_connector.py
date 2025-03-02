import datetime
import logging
import threading
import time
from typing import Dict, List, Optional, Union, Any

from ibapi.client import EClient
from ibapi.contract import Contract, ContractDetails
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from .ibkr_app import IBKRApp
from .data_types import OptionData

class IBKRConnector:
    """
    Connector for Interactive Brokers TWS API
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 7496, client_id: int = 1, paper_trading: bool = True):
        """
        Initialize the connector
        
        Args:
            host: TWS host IP
            port: TWS port
            client_id: Client ID
            paper_trading: If True, orders will be validated but not sent
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.paper_trading = paper_trading
        self.ibkr_app = IBKRApp()
        
        # Set up logging
        self.logger = logging.getLogger("ibkr_connector")
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
        
        # Data caches
        self.contract_details_cache = {}
        self.option_chain_cache = {}
        self.market_data_cache = {}
        self.price_cache = {}
        
        # Connection state
        self._connected = False
        self._reconnect_thread = None
        self._reconnect_interval = 60  # seconds
        self._stop_reconnect = False
        
        self.logger.info(f"IBKRConnector initialized with host {host}, port {port}, client_id {client_id}")
        if self.paper_trading:
            self.logger.info("PAPER TRADING MODE ENABLED - No real orders will be placed")
    
    def connect(self) -> bool:
        """
        Connect to TWS
        
        Returns:
            bool: True if connection successful
        """
        try:
            self.logger.info(f"Connecting to TWS at {self.host}:{self.port}")
            self.ibkr_app.connect(self.host, self.port, self.client_id)
            
            # Start the API event loop in a thread
            api_thread = threading.Thread(target=self._run_client, daemon=True)
            api_thread.start()
            
            # Wait for connection to initialize
            timeout = 10  # seconds
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.ibkr_app.next_order_id is not None:
                    self._connected = True
                    self.logger.info("Successfully connected to TWS")
                    return True
                time.sleep(0.1)
            
            self.logger.error("Connection to TWS timed out")
            return False
        except Exception as e:
            self.logger.error(f"Error connecting to TWS: {str(e)}")
            return False
    
    def _run_client(self):
        """Run the EClient message loop"""
        try:
            self.ibkr_app.run()
        except Exception as e:
            self.logger.error(f"Error in TWS client thread: {str(e)}")
        finally:
            self._connected = False
            self.logger.info("TWS client thread stopped")
            
            # Start reconnect thread if not already running
            if self._reconnect_thread is None and not self._stop_reconnect:
                self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
                self._reconnect_thread.start()
    
    def _reconnect_loop(self):
        """Reconnect loop for automatically reconnecting to TWS"""
        while not self._stop_reconnect:
            if not self._connected:
                self.logger.info(f"Attempting to reconnect to TWS in {self._reconnect_interval} seconds")
                time.sleep(self._reconnect_interval)
                self.connect()
            else:
                time.sleep(5)  # Check connection status periodically
        
        self._reconnect_thread = None
    
    def disconnect(self):
        """Disconnect from TWS"""
        if self._connected:
            self._stop_reconnect = True
            self.ibkr_app.disconnect()
            self._connected = False
            self.logger.info("Disconnected from TWS")
    
    def is_connected(self) -> bool:
        """
        Check if connected to TWS
        
        Returns:
            bool: True if connected
        """
        return self._connected
    
    def get_spx_price(self) -> float:
        """
        Get current SPX price
        
        Returns:
            float: Current SPX price
        """
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return 0.0
        
        # Check cache first
        cache_key = "SPX"
        if cache_key in self.price_cache:
            cache_time, price = self.price_cache[cache_key]
            # Use cache if less than 5 seconds old
            if time.time() - cache_time < 5:
                return price
        
        # Create SPX contract
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        
        # Request market data
        self.ibkr_app.market_data = {}  # Clear previous data
        req_id = 1  # Fixed request ID for SPX price
        
        self.ibkr_app.reqMktData(req_id, contract, "", False, False, [])
        
        # Wait for data
        timeout = 5  # seconds
        start_time = time.time()
        while time.time() - start_time < timeout:
            if req_id in self.ibkr_app.market_data and "last" in self.ibkr_app.market_data[req_id]:
                price = self.ibkr_app.market_data[req_id]["last"]
                # Cache the price
                self.price_cache[cache_key] = (time.time(), price)
                # Cancel market data subscription
                self.ibkr_app.cancelMktData(req_id)
                return price
            time.sleep(0.1)
        
        # If last price not available, try bid/ask average
        if req_id in self.ibkr_app.market_data:
            if "bid" in self.ibkr_app.market_data[req_id] and "ask" in self.ibkr_app.market_data[req_id]:
                bid = self.ibkr_app.market_data[req_id]["bid"]
                ask = self.ibkr_app.market_data[req_id]["ask"]
                price = (bid + ask) / 2
                # Cache the price
                self.price_cache[cache_key] = (time.time(), price)
                # Cancel market data subscription
                self.ibkr_app.cancelMktData(req_id)
                return price
        
        # Cancel market data subscription
        self.ibkr_app.cancelMktData(req_id)
        
        self.logger.warning("Failed to get SPX price")
        return 0.0
    
    def get_contract_details(self, symbol: str, sec_type: str, exchange: str = "SMART", 
                            currency: str = "USD", expiry: str = "", strike: float = 0.0, 
                            right: str = "") -> List[ContractDetails]:
        """
        Get contract details
        
        Args:
            symbol: Contract symbol
            sec_type: Security type (STK, OPT, FUT, IND, etc.)
            exchange: Exchange
            currency: Currency
            expiry: Expiry date in YYYYMMDD format (for options and futures)
            strike: Strike price (for options)
            right: Option right (C or P)
            
        Returns:
            List[ContractDetails]: Contract details
        """
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return []
        
        # Create cache key
        cache_key = f"{symbol}_{sec_type}_{exchange}_{currency}_{expiry}_{strike}_{right}"
        
        # Check cache
        if cache_key in self.contract_details_cache:
            return self.contract_details_cache[cache_key]
        
        # Create contract
        contract = Contract()
        contract.symbol = symbol
        contract.secType = sec_type
        contract.exchange = exchange
        contract.currency = currency
        
        if expiry:
            contract.lastTradeDateOrContractMonth = expiry
        
        if strike > 0:
            contract.strike = strike
        
        if right:
            contract.right = right
        
        # Clear previous contract details
        self.ibkr_app.contract_details = []
        self.ibkr_app.contract_details_end_flag = False
        
        # Request contract details
        req_id = int(time.time()) % 10000  # Use timestamp as request ID
        self.ibkr_app.reqContractDetails(req_id, contract)
        
        # Wait for response
        timeout = 10  # seconds
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.ibkr_app.contract_details_end_flag:
                # Cache the results
                details = self.ibkr_app.contract_details.copy()
                self.contract_details_cache[cache_key] = details
                return details
            time.sleep(0.1)
        
        self.logger.warning(f"Contract details request timed out for {symbol}")
        return []
    
    def get_option_chain(self, symbol, expiry, use_cache=True, timeout=15):
        """
        Get option chain for a symbol and expiry
        
        Args:
            symbol: Symbol
            expiry: Expiry in YYYYMMDD format
            use_cache: Whether to use cached data
            timeout: Timeout in seconds
            
        Returns:
            List[OptionData]: Option chain
        """
        cache_key = f"{symbol}_{expiry}"
        
        if use_cache and cache_key in self.option_chain_cache:
            self.logger.info(f"Using cached option chain for {symbol} {expiry}")
            return self.option_chain_cache[cache_key]
        
        self.logger.info(f"Fetching option chain for {symbol} {expiry}")
        
        if not self.is_connected():
            self.logger.error("Not connected to TWS - cannot get real option data")
            return []
        
        # First, request market data for the underlying (REQUIRED for Greeks)
        underlying_contract = Contract()
        underlying_contract.symbol = symbol
        underlying_contract.secType = "IND" if symbol == "SPX" else "STK"
        underlying_contract.exchange = "CBOE" if symbol == "SPX" else "SMART"
        underlying_contract.currency = "USD"
        
        # Get underlying price
        underlying_id = int(time.time()) % 10000
        self.ibkr_app.reqMktData(underlying_id, underlying_contract, "", False, False, [])
        self.logger.info(f"Requested market data for underlying {symbol}")
        
        time.sleep(1)  # Wait for underlying data
        
        # Create a contract for option chain
        option_contract = Contract()
        option_contract.symbol = symbol
        option_contract.secType = "OPT"
        option_contract.exchange = "SMART"
        option_contract.currency = "USD"
        option_contract.lastTradeDateOrContractMonth = expiry
        option_contract.multiplier = "100"
        
        # Clear existing contract details
        self.ibkr_app.contract_details = []
        self.ibkr_app.contract_details_end_flag = False
        self.ibkr_app.market_data = {}  # Clear previous market data
        
        # Request contract details
        req_id = underlying_id + 1
        self.ibkr_app.reqContractDetails(req_id, option_contract)
        
        # Wait for contract details
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.ibkr_app.contract_details_end_flag:
                break
            time.sleep(0.1)
        
        # If no contracts found, return empty list
        if not self.ibkr_app.contract_details:
            self.logger.error(f"No option contracts found for {symbol} {expiry}")
            self.ibkr_app.cancelMktData(underlying_id)
            return []
        
        option_contracts = []
        for details in self.ibkr_app.contract_details:
            option_contracts.append(details.contract)
        
        self.logger.info(f"Found {len(option_contracts)} option contracts for {symbol} {expiry}")
        
        # Store contracts by conId for later reference
        contract_map = {}
        
        # Request market data for each option contract
        for i, contract in enumerate(option_contracts):
            # Use contract's conId as the request ID
            req_id = contract.conId
            contract_map[req_id] = {
                "contract": contract,
                "option_type": "C" if contract.right == "C" else "P",
                "strike": contract.strike
            }
            
            # Request market data with VALID generic tick types
            # 106 = implied volatility which will trigger Greeks computation
            self.ibkr_app.reqMktData(req_id, contract, "100,101,106", False, False, [])
            
            # Throttle requests to avoid overwhelming TWS
            if i % 50 == 0 and i > 0:
                self.logger.info(f"Requested market data for {i} options, throttling...")
                time.sleep(1)
        
        # Wait for market data to be received
        wait_time = min(timeout, 10)  # Cap the wait time
        self.logger.info(f"Waiting {wait_time} seconds for market data...")
        time.sleep(wait_time)
        
        # Check how many contracts we received delta for
        delta_count = sum(1 for data in self.ibkr_app.market_data.values() if 'delta' in data)
        self.logger.info(f"Received delta for {delta_count}/{len(option_contracts)} options")
        
        # Process received market data into option chain
        option_chain = []
        
        for req_id, data in self.ibkr_app.market_data.items():
            if req_id not in contract_map:
                continue  # Skip unknown contracts
            
            contract_info = contract_map[req_id]
            contract = contract_info["contract"]
            
            # Skip if no delta
            if 'delta' not in data:
                continue
            
            # Get prices
            bid = data.get('bid', 0)
            ask = data.get('ask', 0)
            last = data.get('last', 0)
            
            # Create option data
            option_data = OptionData(
                symbol=contract.symbol,
                expiry=contract.lastTradeDateOrContractMonth,
                strike=contract.strike,
                option_type=contract_info["option_type"],
                bid=bid,
                ask=ask,
                last=last if last > 0 else (bid + ask) / 2 if bid > 0 and ask > 0 else 0,
                volume=data.get('volume', 0),
                open_interest=data.get('open_interest', 0),
                delta=data.get('delta', 0),  # Already converted to absolute value in tickOptionComputation
                gamma=data.get('gamma', 0),
                theta=data.get('theta', 0),
                vega=data.get('vega', 0),
                iv=data.get('iv', 0)
            )
            
            option_chain.append(option_data)
        
        # Cancel all market data subscriptions
        self.ibkr_app.cancelMktData(underlying_id)
        for contract in option_contracts:
            self.ibkr_app.cancelMktData(contract.conId)
        
        # Cache the option chain
        self.option_chain_cache[cache_key] = option_chain
        
        self.logger.info(f"Retrieved {len(option_chain)} options with valid data for {symbol} {expiry}")
        
        # Log some statistics about the deltas
        calls = [opt for opt in option_chain if opt.option_type == "C"]
        puts = [opt for opt in option_chain if opt.option_type == "P"]
        
        if calls:
            call_deltas = [opt.delta for opt in calls]
            self.logger.info(f"Call delta range: {min(call_deltas):.4f} to {max(call_deltas):.4f}")
            
            # Sample deltas sorted by strike
            sorted_calls = sorted(calls, key=lambda x: x.strike)
            sample_calls = [(call.strike, call.delta) for call in sorted_calls[:5]]
            sample_calls += [(call.strike, call.delta) for call in sorted_calls[-5:]]
            self.logger.info(f"Sample call strikes and deltas: {sample_calls}")
        
        if puts:
            put_deltas = [opt.delta for opt in puts]
            self.logger.info(f"Put delta range: {min(put_deltas):.4f} to {max(put_deltas):.4f}")
            
            # Sample deltas sorted by strike
            sorted_puts = sorted(puts, key=lambda x: x.strike)
            sample_puts = [(put.strike, put.delta) for put in sorted_puts[:5]]
            sample_puts += [(put.strike, put.delta) for put in sorted_puts[-5:]]
            self.logger.info(f"Sample put strikes and deltas: {sample_puts}")
        
        return option_chain
    
    def place_order(self, contract: Contract, order: Order) -> int:
        """
        Place an order
        
        Args:
            contract: Contract
            order: Order
            
        Returns:
            int: Order ID or 0 if failed
        """
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return 0
        
        if self.ibkr_app.next_order_id is None:
            self.logger.error("No valid order ID available")
            return 0
        
        # Get next order ID
        order_id = self.ibkr_app.next_order_id
        self.ibkr_app.next_order_id += 1
        
        # Place order (or just log it in paper trading mode)
        if self.paper_trading:
            self.logger.info(f"PAPER TRADE - Order {order_id}: {order.action} {order.totalQuantity} {contract.symbol} @ {order.lmtPrice if hasattr(order, 'lmtPrice') else 'MKT'}")
            # Could add the order to a paper trading simulation here
            return order_id
        else:
            # Place real order
            self.ibkr_app.placeOrder(order_id, contract, order)
            self.logger.info(f"Placed order {order_id}: {order.action} {order.totalQuantity} {contract.symbol}")
        
        return order_id
    
    def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an order
        
        Args:
            order_id: Order ID
            
        Returns:
            bool: True if cancel request sent
        """
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return False
        
        # Send cancel request
        self.ibkr_app.cancelOrder(order_id, "")
        self.logger.info(f"Cancelled order {order_id}")
        
        return True
    
    def get_open_orders(self) -> Dict[int, Dict]:
        """
        Get open orders
        
        Returns:
            Dict[int, Dict]: Dictionary of open orders
        """
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return {}
        
        # Request open orders
        self.ibkr_app.current_orders = {}
        self.ibkr_app.reqOpenOrders()
        
        # Wait for response
        timeout = 5  # seconds
        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(0.5)
        
        return self.ibkr_app.current_orders
    
    def get_account_summary(self) -> Dict:
        """
        Get account summary
        
        Returns:
            Dict: Account summary
        """
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return {}
        
        # Request account summary
        self.ibkr_app.account_summary = {}
        self.ibkr_app.account_ready = False
        req_id = int(time.time()) % 10000  # Use timestamp as request ID
        
        # Request specific account values
        tags = "NetLiquidation,TotalCashValue,SettledCash,AccruedCash,BuyingPower,EquityWithLoanValue"
        self.ibkr_app.reqAccountSummary(req_id, "All", tags)
        
        # Wait for response
        timeout = 5  # seconds
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.ibkr_app.account_ready:
                break
            time.sleep(0.5)
        
        # Cancel request
        self.ibkr_app.cancelAccountSummary(req_id)
        
        return self.ibkr_app.account_summary
    
    def get_positions(self) -> List[Dict]:
        """
        Get positions
        
        Returns:
            List[Dict]: List of positions
        """
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return []
        
        # Request positions
        self.ibkr_app.positions = []
        self.ibkr_app.reqPositions()
        
        # Wait for response
        timeout = 5  # seconds
        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(0.5)
        
        # Cancel request
        self.ibkr_app.cancelPositions()
        
        return self.ibkr_app.positions
    
    def calculate_dte(self, expiry: str) -> int:
        """
        Calculate days to expiration
        
        Args:
            expiry: Expiry date in YYYYMMDD format
            
        Returns:
            int: Days to expiration
        """
        try:
            expiry_date = datetime.datetime.strptime(expiry, "%Y%m%d").date()
            today = datetime.datetime.now().date()
            return max(0, (expiry_date - today).days)
        except ValueError:
            self.logger.error(f"Invalid expiry format: {expiry}")
            return 0
