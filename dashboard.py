import sys
from datetime import datetime, timedelta
import pytz
import time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QGridLayout, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer
from find_delta import (
    is_market_hours,
    execute_dc_config_6,
    ConnectionManager,
    execute_double_calendar,
    get_expiry_from_dte,
    find_target_delta_option
)
from tws_connector import TWSConnector, OptionPosition
from trade_database import TradeDatabase
from trade_scheduler import TradeScheduler
from trade_config import (
    TradeConfig,
    DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3,
    DC_CONFIG_4, DC_CONFIG_5, DC_CONFIG_6,
    CUSTOM_STRANGLE_CONFIG, PUT_FLY_CONFIG
)
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.contract import ComboLeg
import random
import queue

class SimpleManager:
    """A simple manager that wraps TWSConnector for trade execution"""
    def __init__(self, tws):
        self.tws = tws
        # Temporarily disable database
        # self.db = TradeDatabase()  # Add database instance
    
    def get_tws(self):
        return self.tws

def execute_put_fly(connection_manager: ConnectionManager):
    """Execute a Put Butterfly trade if market conditions are met"""
    tws = connection_manager.get_tws()
    if not tws:
        print("No TWS connection available")
        return
        
    try:
        # Get current SPX price with retries
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            # Request SPX price based on market hours
            if is_market_hours():
                print("Market is open - requesting real-time SPX price...")
                tws.reqMktData(1, tws.get_spx_contract(), "", False, False, [])
            else:
                print("Market is closed - requesting previous SPX close...")
                tws.request_spx_historical_data()
            
            # Wait for price with timeout
            timeout = time.time() + 5
            while time.time() < timeout:
                if tws.spx_price is not None:
                    break
                time.sleep(0.1)
            
            if tws.spx_price is not None:
                current_spx = tws.spx_price
                print(f"\nGot SPX price: {current_spx:.2f}")
                break
                
            retry_count += 1
            if retry_count < max_retries:
                print(f"Retry {retry_count}/{max_retries} getting SPX price...")
                time.sleep(2)
        
        if tws.spx_price is None:
            print("Failed to get SPX price after all retries")
            return
            
        print(f"\nExecuting Put Butterfly - Current SPX: {current_spx:.2f}")
        
        # Get expiry based on DTE from config (1DTE normally, 3DTE on Fridays)
        et_now = datetime.now(pytz.timezone('US/Eastern'))
        dte = PUT_FLY_CONFIG.short_dte
        if et_now.weekday() == 4:  # Friday
            dte = 3  # Use 3DTE on Fridays due to weekend
        expiry = get_expiry_from_dte(dte)
        print(f"\nLooking for {dte}DTE options (expiry: {expiry})")
        
        # First, find the put at 0.25 delta
        # Start ~75 points below current price for initial 0.25 delta guess
        initial_strike = round((current_spx - 75) / 5) * 5  # Round to nearest 5
        print(f"\nSearching for 0.25 delta put starting at strike {initial_strike}")
        print(f"({current_spx - initial_strike:.0f} points below current SPX)")
        
        # Create base contract for delta search
        base_contract = Contract()
        base_contract.symbol = "SPX"
        base_contract.secType = "OPT"
        base_contract.exchange = "SMART"
        base_contract.currency = "USD"
        base_contract.right = "P"
        base_contract.strike = initial_strike
        base_contract.lastTradeDateOrContractMonth = expiry
        base_contract.multiplier = "100"
        
        # Don't set tradingClass or localSymbol - let TWS resolve these
        # The contract identifier should be minimal to allow TWS to find the contract
        
        print("\nSearching for initial put with target delta 0.25...")
        print(f"Contract details:")
        print(f"Symbol: {base_contract.symbol}")
        print(f"Strike: {base_contract.strike}")
        print(f"Expiry: {base_contract.lastTradeDateOrContractMonth}")
        print(f"Right: {base_contract.right}")
        print(f"Exchange: {base_contract.exchange}")
        
        # First request contract details
        contract_req_id = tws.get_next_req_id()
        print(f"\nRequesting contract details (reqId: {contract_req_id})")
        tws.reqContractDetails(contract_req_id, base_contract)
        
        # Wait for contract details
        timeout = time.time() + 5
        contract_found = False
        while time.time() < timeout:
            try:
                msg = tws.data_queue.get(timeout=0.1)
                if msg[0] == 'contract_details':
                    _, msg_req_id, contract_details = msg
                    if msg_req_id == contract_req_id:
                        print("Got contract details")
                        base_contract = contract_details.contract
                        contract_found = True
                        break
            except queue.Empty:
                continue
                
        if not contract_found:
            print("Failed to get contract details")
            return
        
        # Now request market data
        req_id = tws.get_next_req_id()
        print(f"\nRequesting market data for initial put (reqId: {req_id})")
        # Request specific tick types:
        # 100: Option Volume
        # 101: Option Open Interest
        # 106: Implied Volatility
        # 236: Inventory
        tws.reqMktData(req_id, base_contract, "100,101,106,236", False, False, [])
        
        # Wait for delta data
        timeout = time.time() + 5
        initial_put = None
        current_strike = initial_strike
        max_attempts = 10  # Prevent infinite loops
        attempts = 0
        
        while attempts < max_attempts:
            try:
                msg = tws.data_queue.get(timeout=0.1)
                if msg[0] == 'option_computation':
                    _, msg_req_id, tick_type, impl_vol, delta, gamma, vega, theta, opt_price = msg
                    if msg_req_id == req_id and delta != -2:
                        print(f"Received delta: {delta:.3f} at strike {current_strike}")
                        
                        # Store this option
                        initial_put = OptionPosition(
                            contract=base_contract,
                            position=0,
                            avg_cost=0,
                            delta=delta
                        )
                        
                        # Calculate how far we are from target
                        delta_diff = abs(abs(delta) - 0.25)
                        
                        # Always check the next strike if we're not exactly at 0.25
                        if abs(delta) != 0.25:
                            # Not close enough - adjust strike and try again
                            current_delta = abs(delta)
                            
                            # Calculate strike adjustment based on how far we are from target
                            delta_diff = 0.25 - current_delta
                            
                            # Rough estimate: every 5-10 points = ~0.01 delta change
                            # So multiply delta difference by 500-1000 for strike adjustment
                            if abs(delta_diff) > 0.1:  # Very far
                                points_per_delta = 750  # More aggressive
                            elif abs(delta_diff) > 0.05:  # Moderately far
                                points_per_delta = 600
                            else:  # Getting close
                                points_per_delta = 500  # More conservative
                                
                            # Calculate strike change
                            strike_change = round(delta_diff * points_per_delta / 5) * 5  # Round to nearest 5
                            
                            print(f"Delta {current_delta:.3f} vs target 0.25 (diff: {delta_diff:.3f})")
                            print(f"Adjusting strike by {strike_change:+d} points")
                            
                            # Cancel current market data request
                            tws.cancelMktData(req_id)
                            
                            # Update strike and request new contract
                            current_strike = current_strike + strike_change
                            base_contract.strike = current_strike
                            
                            # Request contract details for new strike
                            contract_req_id = tws.get_next_req_id()
                            print(f"\nRequesting contract details for strike {current_strike}")
                            tws.reqContractDetails(contract_req_id, base_contract)
                            
                            # Wait for contract details
                            contract_timeout = time.time() + 5
                            contract_found = False
                            while time.time() < contract_timeout:
                                try:
                                    contract_msg = tws.data_queue.get(timeout=0.1)
                                    if contract_msg[0] == 'contract_details':
                                        _, msg_req_id, contract_details = contract_msg
                                        if msg_req_id == contract_req_id:
                                            print("Got contract details")
                                            base_contract = contract_details.contract
                                            contract_found = True
                                            break
                                except queue.Empty:
                                    continue
                                    
                            if not contract_found:
                                print("Failed to get contract details for new strike")
                                break
                                
                            # Request market data for new strike
                            req_id = tws.get_next_req_id()
                            print(f"Requesting market data for strike {current_strike}")
                            tws.reqMktData(req_id, base_contract, "100,101,106,236", False, False, [])
                            attempts += 1
                            continue
                        else:
                            print(f"Found exact target delta: {delta:.3f}")
                            break
                        
            except queue.Empty:
                continue
                
            attempts += 1
        
        # Cancel final market data request
        tws.cancelMktData(req_id)
        
        if not initial_put or initial_put.delta is None:
            print("\nFailed to get delta for initial put. Possible reasons:")
            print("1. No market data subscription for SPX options")
            print("2. Option chain not available for specified expiry")
            print("3. Connection issues with TWS")
            return
            
        print(f"\nFound initial put - Strike: {initial_put.contract.strike}, Delta: {initial_put.delta:.3f}")
        
        # Calculate strikes for other legs
        short_strike = initial_put.contract.strike - PUT_FLY_CONFIG.put_width
        far_strike = initial_put.contract.strike - PUT_FLY_CONFIG.call_width
        
        print("\nCalculating butterfly legs:")
        print(f"Long Put Strike: {initial_put.contract.strike}")
        print(f"Short Put Strike: {short_strike} (x2)")
        print(f"Far Put Strike: {far_strike}")
        
        # Get contracts for other legs with same expiry
        print("\nGetting contracts for other legs...")
        
        # Short puts
        short_contract = Contract()
        short_contract.symbol = "SPX"
        short_contract.secType = "OPT"
        short_contract.exchange = "SMART"
        short_contract.currency = "USD"
        short_contract.right = "P"
        short_contract.strike = short_strike
        short_contract.lastTradeDateOrContractMonth = expiry
        short_contract.multiplier = "100"
        
        # Get contract details for short puts
        contract_req_id = tws.get_next_req_id()
        print(f"\nRequesting contract details for short puts (reqId: {contract_req_id})")
        tws.reqContractDetails(contract_req_id, short_contract)
        
        # Wait for contract details
        timeout = time.time() + 5
        contract_found = False
        while time.time() < timeout:
            try:
                msg = tws.data_queue.get(timeout=0.1)
                if msg[0] == 'contract_details':
                    _, msg_req_id, contract_details = msg
                    if msg_req_id == contract_req_id:
                        print("Got contract details for short puts")
                        short_contract = contract_details.contract
                        contract_found = True
                        break
            except queue.Empty:
                continue
                
        if not contract_found:
            print("Failed to get contract details for short puts")
            return
        
        # Far put
        far_contract = Contract()
        far_contract.symbol = "SPX"
        far_contract.secType = "OPT"
        far_contract.exchange = "SMART"
        far_contract.currency = "USD"
        far_contract.right = "P"
        far_contract.strike = far_strike
        far_contract.lastTradeDateOrContractMonth = expiry
        far_contract.multiplier = "100"
        
        # Get contract details for far put
        contract_req_id = tws.get_next_req_id()
        print(f"\nRequesting contract details for far put (reqId: {contract_req_id})")
        tws.reqContractDetails(contract_req_id, far_contract)
        
        # Wait for contract details
        timeout = time.time() + 5
        contract_found = False
        while time.time() < timeout:
            try:
                msg = tws.data_queue.get(timeout=0.1)
                if msg[0] == 'contract_details':
                    _, msg_req_id, contract_details = msg
                    if msg_req_id == contract_req_id:
                        print("Got contract details for far put")
                        far_contract = contract_details.contract
                        contract_found = True
                        break
            except queue.Empty:
                continue
                
        if not contract_found:
            print("Failed to get contract details for far put")
            return
        
        # Get prices for all legs
        print("\nGetting prices for all legs...")
        initial_price = tws.get_option_price(initial_put.contract)
        short_price = tws.get_option_price(short_contract)
        far_price = tws.get_option_price(far_contract)
        
        if initial_price == 0 or short_price == 0 or far_price == 0:
            print("Failed to get prices for all legs")
            return
        
        # Calculate total credit (Long wings - Short body)
        total_credit = (initial_price + far_price) - (2 * short_price)
        
        print("\n" + "="*50)
        print("🦋 PUT BUTTERFLY SUMMARY")
        print("="*50)
        print(f"SPX Price: {current_spx:.2f}")
        print(f"Expiry: {expiry} ({dte}DTE)")
        print(f"\nLong Put Strike: {initial_put.contract.strike} @ {initial_price:.2f}")
        print(f"Delta: {initial_put.delta:.3f}")
        print(f"Short Put Strike: {short_strike} @ {short_price:.2f} (x2)")
        print(f"Far Put Strike: {far_strike} @ {far_price:.2f}")
        print(f"\nTotal Credit: {total_credit:.2f}")
        
        # Check if credit is sufficient (remember, more negative is better for credit)
        if total_credit > -PUT_FLY_CONFIG.min_credit:
            print(f"\nCredit {total_credit:.2f} insufficient (need at least {-PUT_FLY_CONFIG.min_credit:.2f}) - Skipping trade")
            return
            
        # Create combo legs for butterfly
        combo_legs = []
        
        # Long put (first wing)
        leg1 = ComboLeg()
        leg1.conId = initial_put.contract.conId
        leg1.ratio = 1
        leg1.action = "BUY"
        leg1.exchange = "SMART"
        
        # Short puts (body)
        leg2 = ComboLeg()
        leg2.conId = short_contract.conId
        leg2.ratio = 2
        leg2.action = "SELL"
        leg2.exchange = "SMART"
        
        # Long put (second wing)
        leg3 = ComboLeg()
        leg3.conId = far_contract.conId
        leg3.ratio = 1
        leg3.action = "BUY"
        leg3.exchange = "SMART"
        
        combo_legs.extend([leg1, leg2, leg3])
        
        # Create the BAG contract
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "BAG"
        contract.currency = "USD"
        contract.exchange = "SMART"
        contract.comboLegs = combo_legs
        
        # Create the order
        order = Order()
        order.orderType = "LMT"
        order.totalQuantity = PUT_FLY_CONFIG.quantity
        order.lmtPrice = total_credit  # Using positive price for credit
        order.action = "SELL"  # SELL the butterfly to receive credit
        order.tif = "DAY"
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        
        # Submit the order
        order_id = tws.next_order_id
        tws.next_order_id += 1
        
        print("\nSubmitting Put Butterfly order:")
        print(f"Order ID: {order_id}")
        print(f"Quantity: {PUT_FLY_CONFIG.quantity}")
        print(f"Credit: {total_credit:.2f}")
        
        tws.placeOrder(order_id, contract, order)
        print("\nOrder submitted - monitoring for 5 minutes...")
        
        # Monitor order status
        if not tws.monitor_order(order_id, timeout_seconds=300):
            print("\nOrder not filled after 5 minutes - canceling")
            tws.cancel_order(order_id)
            return
            
        print("\nPut Butterfly order filled successfully!")
        
    except Exception as e:
        print(f"Error executing Put Butterfly: {str(e)}")

class TradingDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SPX Trading Dashboard")
        self.resize(800, 600)
        
        # Initialize components
        self.connection_manager = None  # Will hold ConnectionManager instance
        self.running = False
        self.last_price_update = 0
        self.price_update_interval = 1  # seconds
        self.start_time = time.time()
        
        # Create delta functions
        def get_put_delta():
            return 0.25
            
        def get_call_delta():
            return 0.25
            
        # Store the functions as instance variables
        self.get_put_delta = get_put_delta
        self.get_call_delta = get_call_delta
        
        # Create UI
        self.setup_ui()
        
        # Create timers
        self.connection_timer = QTimer()
        self.connection_timer.timeout.connect(self.check_connection)
        
        self.price_timer = QTimer()
        self.price_timer.timeout.connect(self.update_prices)
        
        # Setup close handling
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    
    def check_connection(self):
        """Check TWS connection status and reestablish market data if needed"""
        try:
            if not self.running or not self.connection_manager:
                return
                
            is_connected = self.connection_manager.check_connection()
            
            if is_connected:
                self.connection_status.setText("✅ CONNECTED")
                
                # Check if we need to resubscribe to market data
                tws = self.connection_manager.tws
                if tws:
                    # For SPX: Check market hours and request appropriate data
                    spx_needs_update = (not hasattr(tws, 'spx_price') or 
                                      time.time() - self.last_price_update > 5)
                    if spx_needs_update:
                        print("Resubscribing to SPX data...")
                        try:
                            tws.cancelMktData(1)
                        except:
                            pass
                        time.sleep(0.1)
                        
                        # Get current time in ET
                        now = datetime.now(pytz.timezone('US/Eastern'))
                        is_rth = (now.hour >= 9 and now.minute >= 30) and (now.hour < 16)
                        
                        if is_rth:
                            print("Market is open - requesting real-time SPX data...")
                            tws.reqMktData(1, tws.get_spx_contract(), "", False, False, [])
                        else:
                            print("Market is closed - requesting SPX historical data...")
                            tws.request_spx_historical_data()
                    
                    # For ES: Always need real-time data
                    es_needs_update = (not hasattr(tws, 'es_price') or 
                                     time.time() - self.last_price_update > 5)
                    if es_needs_update:
                        print("Resubscribing to ES data...")
                        try:
                            tws.cancelMktData(2)
                        except:
                            pass
                        time.sleep(0.1)
                        tws.request_es_data()
                
                if not self.price_timer.isActive():
                    self.price_timer.start(1000)
            else:
                self.connection_status.setText("❌ DISCONNECTED")
                self.price_timer.stop()
            
        except Exception as e:
            print(f"Error checking connection: {str(e)}")
    
    def update_prices(self):
        """Update price displays"""
        try:
            if not self.running or not self.connection_manager or not self.connection_manager.tws:
                return
                
            current_time = time.time()
            if current_time - self.last_price_update < self.price_update_interval:
                return
                
            # Update SPX price
            if hasattr(self.connection_manager.tws, 'spx_price'):
                try:
                    spx_price = float(self.connection_manager.tws.spx_price)
                    self.spx_price.setText(f"{spx_price:.2f}")
                except (ValueError, TypeError) as e:
                    pass
            
            # Update ES price
            if hasattr(self.connection_manager.tws, 'es_price'):
                try:
                    es_price = float(self.connection_manager.tws.es_price)
                    self.es_price.setText(f"{es_price:.2f}")
                except (ValueError, TypeError) as e:
                    pass
            
            self.last_price_update = current_time
            
        except Exception as e:
            pass
    
    def get_es_contract(self):
        """Get the active ES futures contract"""
        es_contract = Contract()
        es_contract.symbol = "ES"
        es_contract.secType = "FUT"
        es_contract.exchange = "CME"
        es_contract.currency = "USD"
        
        # Calculate next quarterly expiry (Mar, Jun, Sep, Dec)
        now = datetime.now()
        month = now.month
        year = now.year
        
        # Find next expiry month
        if month < 3:
            expiry_month = "03"
        elif month < 6:
            expiry_month = "06"
        elif month < 9:
            expiry_month = "09"
        elif month < 12:
            expiry_month = "12"
        else:  # December, so use March next year
            expiry_month = "03"
            year += 1
            
        es_contract.lastTradeDateOrContractMonth = f"{year}{expiry_month}"
        
        # Comment out debug prints
        # print("\nES Contract Details:")
        # print(f"Symbol: {es_contract.symbol}")
        # print(f"SecType: {es_contract.secType}")
        # print(f"Exchange: {es_contract.exchange}")
        # print(f"Currency: {es_contract.currency}")
        # print(f"LastTradeDate: {es_contract.lastTradeDateOrContractMonth}")
        
        return es_contract
    
    def start_trading(self):
        if not self.running:
            try:
                print("Starting trading system...")
                self.running = True
                self.last_price_update = 0
                
                # Initialize connection manager for UI updates
                print("Initializing connection manager...")
                self.connection_manager = ConnectionManager(client_id=0, check_interval=0)
                
                print("Waiting for connection to stabilize...")
                time.sleep(5)
                
                if not self.connection_manager.tws or not self.connection_manager.tws.isConnected():
                    raise Exception("Failed to establish stable connection")
                
                # Initialize scheduler
                self.scheduler = TradeScheduler()
                
                # Schedule the Put Butterfly for 3 minutes from now
                current_time = datetime.now(pytz.timezone('US/Eastern'))
                test_time = (current_time + timedelta(minutes=3)).strftime("%H:%M")
                current_day = current_time.strftime('%A')
                print(f"\nScheduling Put Butterfly for today ({current_day}) at {test_time} ET")
                self.scheduler.add_trade(
                    time_et=test_time,
                    trade_name=PUT_FLY_CONFIG.trade_name,
                    trade_func=lambda: execute_put_fly(self.connection_manager),
                    day=current_day  # Explicitly set today's day
                )
                
                # Schedule the IC trade for today at 14:05 ET
                self.scheduler.add_trade(
                    time_et="14:05",
                    trade_name="IC_0DTE_160130_30",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=CUSTOM_STRANGLE_CONFIG),
                    day="Wednesday"
                )
                
                # Schedule other trades
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG.trade_name,
                    time_et="10:15",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=DC_CONFIG),
                    day="Friday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_2.trade_name,
                    time_et="11:55",
                    trade_func=lambda: execute_dc_config_2(self.connection_manager),
                    day="Friday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_3.trade_name,
                    time_et="13:00",
                    trade_func=lambda: execute_dc_config_3(self.connection_manager),
                    day="Friday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_4.trade_name,
                    time_et="14:10",
                    trade_func=lambda: execute_dc_config_4(self.connection_manager),
                    day="Friday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_5.trade_name,
                    time_et="12:00",
                    trade_func=lambda: execute_dc_config_5(self.connection_manager),
                    day="Monday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_6.trade_name,
                    time_et="13:30",
                    trade_func=lambda: execute_dc_config_6(self.connection_manager),
                    day="Monday"
                )
                
                # List all scheduled trades
                self.scheduler.list_trades()
                
                print("System ready - monitoring for scheduled trades")
                
                # Start timers
                self.connection_timer.start(1000)  # Check connection every second
                self.status_timer = QTimer()
                self.status_timer.timeout.connect(self.update_status)
                self.status_timer.start(1000)
                
                # Update UI
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                
                # Initial market data setup
                print("Setting up initial market data...")
                self.check_connection()  # This will establish initial subscriptions
                
                print("Trading system startup complete")
                
            except Exception as e:
                print(f"Error in start_trading: {str(e)}")
                self.emergency_stop()
    
    def update_status(self):
        """Update market hours and other status information"""
        try:
            if not self.running:
                return
            
            # Update market hours
            market_open = is_market_hours()
            self.market_hours.setText("Yes" if market_open else "No")
            
            # Update uptime
            if hasattr(self, 'start_time'):
                uptime_seconds = int(time.time() - self.start_time)
                uptime_hours = uptime_seconds // 3600
                uptime_minutes = (uptime_seconds % 3600) // 60
                self.uptime.setText(f"{uptime_hours}h {uptime_minutes}m")
            
            # Run scheduler
            if hasattr(self, 'scheduler'):
                self.scheduler.run()
                
                # Update next trade display
                next_trade = self.scheduler.get_next_trade()
                if next_trade:
                    self.next_trade.setText(f"{next_trade['day']} {next_trade['time_et']} ET - {next_trade['name']}")
                else:
                    self.next_trade.setText("None")
        
        except Exception as e:
            print(f"Error updating status: {str(e)}")
    
    def emergency_stop(self):
        print("Emergency stop initiated...")
        try:
            self.running = False
            
            # Stop all timers
            self.connection_timer.stop()
            self.price_timer.stop()
            if hasattr(self, 'status_timer'):
                self.status_timer.stop()
            
            # Disconnect using connection manager
            if self.connection_manager:
                try:
                    self.connection_manager.disconnect()
                except Exception as e:
                    print(f"Error disconnecting TWS: {str(e)}")
            
            # Reset components
            self.connection_manager = None
            self.last_price_update = 0
            
            # Update UI
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.connection_status.setText("❌ DISCONNECTED")
            self.market_hours.setText("No")
            self.spx_price.setText("---.--")
            self.es_price.setText("---.--")
            self.next_trade.setText("None")
            self.uptime.setText("0h 0m")
            
        except Exception as e:
            print(f"Error in emergency_stop: {str(e)}")
    
    def closeEvent(self, event):
        print("Close event received...")
        if self.running:
            self.emergency_stop()
        event.accept()
        print("Close event completed")

    def setup_ui(self):
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Control Section
        control_group = QGroupBox("System Control")
        control_layout = QHBoxLayout()
        
        self.start_button = QPushButton("Start Trading System")
        self.start_button.clicked.connect(self.start_trading)
        
        self.stop_button = QPushButton("Stop Trading System")
        self.stop_button.clicked.connect(self.emergency_stop)
        self.stop_button.setEnabled(False)
        
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # Status and Trades Section
        status_trades_layout = QHBoxLayout()
        
        # Status Section
        status_group = QGroupBox("System Status")
        status_layout = QGridLayout()
        
        self.connection_status = QLabel("❌ DISCONNECTED")
        self.market_hours = QLabel("No")
        self.spx_price = QLabel("---.--")
        self.es_price = QLabel("---.--")
        self.next_trade = QLabel("None")
        self.uptime = QLabel("0h 0m")
        
        status_layout.addWidget(QLabel("Connection:"), 0, 0)
        status_layout.addWidget(self.connection_status, 0, 1)
        status_layout.addWidget(QLabel("Market Hours:"), 1, 0)
        status_layout.addWidget(self.market_hours, 1, 1)
        status_layout.addWidget(QLabel("SPX:"), 2, 0)
        status_layout.addWidget(self.spx_price, 2, 1)
        status_layout.addWidget(QLabel("ES:"), 3, 0)
        status_layout.addWidget(self.es_price, 3, 1)
        status_layout.addWidget(QLabel("Next Trade:"), 4, 0)
        status_layout.addWidget(self.next_trade, 4, 1)
        status_layout.addWidget(QLabel("Uptime:"), 5, 0)
        status_layout.addWidget(self.uptime, 5, 1)
        
        status_group.setLayout(status_layout)
        status_trades_layout.addWidget(status_group)
        
        # Recent Trades Section
        trades_group = QGroupBox("Recent Trades")
        trades_layout = QVBoxLayout()
        
        self.trades_tree = QTreeWidget()
        self.trades_tree.setHeaderLabels(["Time", "Trade", "Status"])
        self.trades_tree.setColumnCount(3)
        
        trades_layout.addWidget(self.trades_tree)
        trades_group.setLayout(trades_layout)
        status_trades_layout.addWidget(trades_group)
        
        layout.addLayout(status_trades_layout)
        
        # Log Section
        log_group = QGroupBox("System Log")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # Set minimum size for stability
        self.setMinimumSize(800, 600)

def main():
    app = QApplication(sys.argv)
    window = TradingDashboard()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 