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
    """
    Execute a 1DTE Put Butterfly trade as a credit spread.
    
    Trade structure:
      • Leg1: Buy 1 put (long) with ~25 delta.
      • Leg2: Sell 2 puts at a strike 10 points lower than Leg1.
      • Leg3: Buy 1 put at a strike 50 points lower than Leg1.
      
    Minimum acceptable credit: 1.30.
    (Note: Credits are expressed as negative numbers; e.g., -3.00 offers more credit than -1.30.)
    
    For testing we ignore market/timing conditions; in production,
    execute only at Wed/Thu/Fri 15:45 if the market is up.
    
    IBKR requires combo orders for credit trades to be submitted as BUY orders at negative prices.
    """
    tws = connection_manager.get_tws()
    if not tws:
        print("No TWS connection available")
        return

    try:
        # --------------------- Step 1: Get Current Market Price ---------------------
        max_retries = 3
        retry_count = 0
        current_spx = None
        while retry_count < max_retries:
            print("Requesting SPX price...")
            # For testing, bypass market-time logic:
            if is_market_hours():
                tws.reqMktData(1, tws.get_spx_contract(), "", False, False, [])
            else:
                tws.request_spx_historical_data()
            timeout = time.time() + 5
            while time.time() < timeout:
                if tws.spx_price is not None:
                    current_spx = tws.spx_price
                    break
                time.sleep(0.1)
            if current_spx is not None:
                print(f"Got SPX price: {current_spx:.2f}")
                break
            retry_count += 1
            print(f"Retry {retry_count}/{max_retries} getting SPX price...")
            time.sleep(2)
        if current_spx is None:
            print("Failed to get SPX price")
            return

        # ------------------ Step 2: Determine Option Expiry ------------------
        et_now = datetime.now(pytz.timezone('US/Eastern'))
        dte = 1
        if et_now.weekday() == 4:  # Friday
            dte = 3
        expiry = get_expiry_from_dte(dte)
        print(f"Using expiry: {expiry} for {dte}DTE")
        
        # ------------------ Step 3: Find the 25 Delta Put ------------------
        target_delta = 0.25       # Desired absolute delta
        acceptable_diff = 0.02    # Acceptable margin (±0.02)
        initial_strike = round((current_spx - 300) / 5) * 5  
        print(f"Searching for 25δ put starting at strike {initial_strike} " +
              f"({current_spx - initial_strike:.0f} points OTM)")
        
        current_strike_found = initial_strike
        max_attempts = 20
        attempts = 0
        found_put = None

        while attempts < max_attempts:
            # Get option chain for current strike
            print(f"\nRequesting option chain for strike {current_strike_found}")
            options = tws.request_option_chain(expiry, "P", current_strike_found, current_strike_found)
            
            if not options:
                print("No options found at this strike")
                break
            
            # Get delta directly from the option chain data
            current_delta = options[0].delta if options[0].delta is not None else 0
            print(f"At strike {current_strike_found}: Got delta {current_delta:.3f}")
            
            # Check if we're within acceptable range
            if abs(abs(current_delta) - target_delta) < acceptable_diff:
                print(f"Found target delta! Strike: {current_strike_found}, Delta: {current_delta:.3f}")
                found_put = options[0]
                break
            
            # Calculate how far off we are
            diff = abs(abs(current_delta) - target_delta)
            
            # Adaptive step size based on how far we are from target
            if diff > 0.1:
                step = 20
            elif diff > 0.05:
                step = 10
            else:
                step = 5
            
            if abs(current_delta) < target_delta:
                # Delta too low (not negative enough) -> move higher
                print(f"Delta too low (|{current_delta:.3f}| < {target_delta}); increasing strike by {step}")
                current_strike_found += step
            else:
                # Delta too high -> move lower
                print(f"Delta too high (|{current_delta:.3f}| > {target_delta}); decreasing strike by {step}")
                current_strike_found -= step
            
            attempts += 1

        if not found_put:
            print("Failed to find 25δ put within max attempts")
            return

        print(f"\nSelected put strike: {found_put.contract.strike}")
        print(f"Delta: {found_put.delta:.3f}")
        
        # ------------------ Step 4: Define the Other Legs ------------------
        # Leg1 (Long): The found 25δ put.
        long_put_strike = found_put.contract.strike
        # Leg2 (Short): Put 10 points lower.
        short_put_strike = long_put_strike - 10
        # Leg3 (Far Long): Put 50 points lower than the long put strike.
        far_put_strike = long_put_strike - 50
        
        print("Trade Legs:")
        print(f"  • Long put at {long_put_strike}")
        print(f"  • Short put at {short_put_strike} (x2)")
        print(f"  • Far long put at {far_put_strike}")
        
        # Create contracts for the short and far legs.
        short_contract = Contract()
        short_contract.symbol = "SPX"
        short_contract.secType = "OPT"
        short_contract.exchange = "SMART"
        short_contract.currency = "USD"
        short_contract.right = "P"
        short_contract.strike = short_put_strike
        short_contract.lastTradeDateOrContractMonth = expiry
        short_contract.multiplier = "100"
        
        far_contract = Contract()
        far_contract.symbol = "SPX"
        far_contract.secType = "OPT"
        far_contract.exchange = "SMART"
        far_contract.currency = "USD"
        far_contract.right = "P"
        far_contract.strike = far_put_strike
        far_contract.lastTradeDateOrContractMonth = expiry
        far_contract.multiplier = "100"
        
        print("Retrieving market prices for legs...")
        initial_price = tws.get_option_price(found_put.contract)
        short_price = tws.get_option_price(short_contract)
        far_price = tws.get_option_price(far_contract)
        
        if initial_price == 0 or short_price == 0 or far_price == 0:
            print("Failed to retrieve option prices for one or more legs.")
            return
        
        print(f"Leg Prices: Long: {initial_price:.2f}, Short: {short_price:.2f}, Far: {far_price:.2f}")
        
        # Calculate net credit: (Long leg + Far leg) - (2 x Short leg).
        total_credit = (initial_price + far_price) - (2 * short_price)
        print(f"Total Credit: {total_credit:.2f}")
        
        if total_credit > -PUT_FLY_CONFIG.min_credit:
            print(f"Credit {total_credit:.2f} insufficient " +
                  f"(min required is {-PUT_FLY_CONFIG.min_credit:.2f}). Aborting trade.")
            return

        # ------------------ Step 5: Construct and Submit the Combo Order ------------------
        print("Constructing combo order...")
        combo_legs = []
        
        # Leg1: Buy 1 put at the 25δ strike.
        leg1 = ComboLeg()
        leg1.conId = found_put.contract.conId
        leg1.ratio = 1
        leg1.action = "BUY"
        leg1.exchange = "SMART"
        combo_legs.append(leg1)
        
        # Leg2: Sell 2 puts at 10 points lower.
        leg2 = ComboLeg()
        leg2.conId = short_contract.conId
        leg2.ratio = 2
        leg2.action = "SELL"
        leg2.exchange = "SMART"
        combo_legs.append(leg2)
        
        # Leg3: Buy 1 put at 50 points lower.
        leg3 = ComboLeg()
        leg3.conId = far_contract.conId
        leg3.ratio = 1
        leg3.action = "BUY"
        leg3.exchange = "SMART"
        combo_legs.append(leg3)
        
        # Build the combo contract.
        combo_contract = Contract()
        combo_contract.symbol = "SPX"
        combo_contract.secType = "BAG"
        combo_contract.currency = "USD"
        combo_contract.exchange = "SMART"
        combo_contract.comboLegs = combo_legs
        
        # For a credit spread, IBKR requires the order to be entered with a negative price.
        order = Order()
        order.orderType = "LMT"
        order.totalQuantity = PUT_FLY_CONFIG.quantity
        order.lmtPrice = total_credit  # Expected to be negative, e.g., -3.00
        order.action = "BUY"  # IBKR requires combo credits to be entered as a BUY at a negative price
        order.tif = "DAY"
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        
        order_id = random.randint(10000, 99999)
        tws.next_order_id += 1
        
        print(f"Submitting combo order with Order ID: {order_id}")
        tws.placeOrder(order_id, combo_contract, order)
        print("Order submitted. Monitoring order status for 5 minutes...")
        
        if not tws.monitor_order(order_id, timeout_seconds=300):
            print("Order not filled after 5 minutes, cancelling...")
            tws.cancel_order(order_id)
            return
        print("Put Butterfly order filled successfully!")
        
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
                            # Request all data by using empty string for generic ticks
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
                
                # Schedule the Put Butterfly for testing
                current_time = datetime.now(pytz.timezone('US/Eastern'))
                test_time = (current_time + timedelta(minutes=3)).strftime("%H:%M")
                current_day = current_time.strftime('%A')
                print(f"\nScheduling Put Butterfly for today ({current_day}) at {test_time} ET")
                self.scheduler.add_trade(
                    time_et=test_time,
                    trade_name=PUT_FLY_CONFIG.trade_name,
                    trade_func=lambda: execute_put_fly(self.connection_manager),
                    day=current_day
                )
                
                # Schedule Double Calendar trades using execute_double_calendar with appropriate configs
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG.trade_name,
                    time_et="10:15",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=DC_CONFIG),
                    day="Friday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_2.trade_name,
                    time_et="11:55",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=DC_CONFIG_2),
                    day="Friday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_3.trade_name,
                    time_et="13:00",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=DC_CONFIG_3),
                    day="Friday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_4.trade_name,
                    time_et="14:10",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=DC_CONFIG_4),
                    day="Friday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_5.trade_name,
                    time_et="12:00",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=DC_CONFIG_5),
                    day="Monday"
                )
                
                self.scheduler.add_trade(
                    trade_name=DC_CONFIG_6.trade_name,
                    time_et="13:30",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=DC_CONFIG_6),
                    day="Monday"
                )
                
                # Schedule the IC trade
                self.scheduler.add_trade(
                    time_et="14:05",
                    trade_name="IC_0DTE_160130_30",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=CUSTOM_STRANGLE_CONFIG),
                    day="Wednesday"
                )
                
                # List all scheduled trades
                self.scheduler.list_trades()
                
                print("System ready - monitoring for scheduled trades")
                
                # Start timers
                self.connection_timer.start(1000)
                self.status_timer = QTimer()
                self.status_timer.timeout.connect(self.update_status)
                self.status_timer.start(1000)
                
                # Update UI
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                
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