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
    execute_double_calendar
)
from tws_connector import TWSConnector
from trade_database import TradeDatabase
from trade_scheduler import TradeScheduler
from trade_config import (
    TradeConfig,
    DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3,
    DC_CONFIG_4, DC_CONFIG_5, DC_CONFIG_6,
    CUSTOM_STRANGLE_CONFIG
)
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
import random

class SimpleManager:
    """A simple manager that wraps TWSConnector for trade execution"""
    def __init__(self, tws):
        self.tws = tws
        # Temporarily disable database
        # self.db = TradeDatabase()  # Add database instance
    
    def get_tws(self):
        return self.tws

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
        """Check TWS connection status"""
        try:
            if not self.running or not self.connection_manager:
                return
                
            is_connected = self.connection_manager.check_connection()
            
            if is_connected:
                self.connection_status.setText("✅ CONNECTED")
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
                
            if hasattr(self.connection_manager.tws, 'spx_price'):
                try:
                    self.spx_price.setText(f"{float(self.connection_manager.tws.spx_price):.2f}")
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
                
                # Schedule the IC trade for today at 14:05 ET
                self.scheduler.add_trade(
                    time_et="14:05",
                    trade_name="IC_0DTE_160130_30",  # Format: IC_DTE_PutPremCallPrem_Width
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=CUSTOM_STRANGLE_CONFIG),
                    day="Wednesday"  # Specify today
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
                
                # Start timers only after connection is stable
                self.connection_timer.start(1000)
                self.status_timer = QTimer()
                self.status_timer.timeout.connect(self.update_status)
                self.status_timer.start(1000)
                
                # Update UI
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                
                # Setup market data based on market hours
                print("Setting up market data...")
                try:
                    now = datetime.now(pytz.timezone('US/Eastern'))
                    is_rth = (now.hour >= 9 and now.minute >= 30) and now.hour < 16
                    
                    if is_rth:
                        print("In RTH - requesting real-time SPX data...")
                        self.connection_manager.tws.request_spx_data()
                    else:
                        print("Outside RTH - requesting historical SPX data...")
                        self.connection_manager.tws.request_spx_historical_data()
                    time.sleep(3)
                    
                except Exception as e:
                    print(f"Error setting up market data: {str(e)}")
                
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