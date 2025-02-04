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
    ConnectionManager,
    execute_double_calendar,
    execute_dc_config_2,
    execute_dc_config_3,
    execute_dc_config_4,
    execute_dc_config_5,
    execute_dc_config_6
)
from trade_database import TradeDatabase
from trade_scheduler import TradeScheduler
from trade_config import (
    DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3,
    DC_CONFIG_4, DC_CONFIG_5, DC_CONFIG_6,
    CUSTOM_STRANGLE_CONFIG
)
from ibapi.contract import Contract
from ibapi.order import Order

class TradingDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SPX Trading Dashboard")
        self.resize(800, 600)
        
        # Initialize components
        self.connection_manager = None
        self.running = False
        self.last_price_update = 0
        self.price_update_interval = 1  # seconds
        self.start_time = time.time()  # Added start time tracking
        
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
                
            is_connected = self.connection_manager.tws.isConnected()
            
            if is_connected:
                self.connection_status.setText("✅ CONNECTED")
                # Start price updates if not already started
                if not self.price_timer.isActive():
                    self.price_timer.start(1000)  # Update prices every second
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
                
            # Only update if enough time has passed
            current_time = time.time()
            if current_time - self.last_price_update < self.price_update_interval:
                return
                
            # Update SPX price if available
            if hasattr(self.connection_manager.tws, 'spx_price') and self.connection_manager.tws.spx_price is not None:
                try:
                    self.spx_price.setText(f"{float(self.connection_manager.tws.spx_price):.2f}")
                except (ValueError, TypeError) as e:
                    print(f"Error formatting SPX price: {e}")
            
            # Update ES price if available
            if hasattr(self.connection_manager.tws, 'es_price') and self.connection_manager.tws.es_price is not None:
                try:
                    self.es_price.setText(f"{float(self.connection_manager.tws.es_price):.2f}")
                except (ValueError, TypeError) as e:
                    print(f"Error formatting ES price: {e}")
            
            self.last_price_update = current_time
            
        except Exception as e:
            print(f"Error updating prices: {str(e)}")
    
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
        
        print("\nES Contract Details:")
        print(f"Symbol: {es_contract.symbol}")
        print(f"SecType: {es_contract.secType}")
        print(f"Exchange: {es_contract.exchange}")
        print(f"Currency: {es_contract.currency}")
        print(f"LastTradeDate: {es_contract.lastTradeDateOrContractMonth}")
        
        return es_contract
    
    def start_trading(self):
        if not self.running:
            try:
                print("Starting trading system...")
                self.running = True
                self.last_price_update = 0
                
                # Initialize connection manager
                print("Initializing connection manager...")
                self.connection_manager = ConnectionManager(client_id=99, check_interval=180)
                
                # Request market data for SPX and ES
                print("Requesting market data...")
                if hasattr(self.connection_manager, 'tws'):
                    # Cancel any existing market data requests
                    try:
                        self.connection_manager.tws.cancelMktData(1)  # Cancel SPX data
                        self.connection_manager.tws.cancelMktData(2)  # Cancel ES data
                        time.sleep(1)  # Give time for cancellations to process
                    except Exception as e:
                        print(f"Error canceling market data: {str(e)}")
                    
                    # Request SPX data
                    spx_contract = self.connection_manager.tws.get_spx_contract()
                    self.connection_manager.tws.reqMktData(1, spx_contract, "", False, False, [])
                    
                    # Request ES data
                    es_contract = self.get_es_contract()
                    print("Requesting ES futures market data...")
                    self.connection_manager.tws.reqMktData(2, es_contract, "", False, False, [])
                
                # Initialize scheduler
                print("Initializing trade scheduler...")
                self.scheduler = TradeScheduler()
                
                # Schedule custom strangle for 11:35 ET
                print("Scheduling custom strangle for 11:35 ET")
                self.scheduler.add_trade(
                    trade_name=CUSTOM_STRANGLE_CONFIG.trade_name,
                    time_et="11:35",
                    trade_func=lambda: execute_double_calendar(self.connection_manager, config=CUSTOM_STRANGLE_CONFIG),
                    day=datetime.now(pytz.timezone('US/Eastern')).strftime('%A')
                )
                
                # Start timers
                self.connection_timer.start(1000)  # Check every second
                self.status_timer = QTimer()  # New timer for market hours
                self.status_timer.timeout.connect(self.update_status)
                self.status_timer.start(1000)  # Update every second
                
                # Update UI
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                print("Trading system startup complete")
                self.scheduler.list_trades()  # Show scheduled trades
                
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
            
            # Run scheduler if market is open
            if market_open and hasattr(self, 'scheduler'):
                self.scheduler.run()
            
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
            
            # Cancel market data subscriptions
            if self.connection_manager and self.connection_manager.tws:
                try:
                    self.connection_manager.tws.cancelMktData(1)  # Cancel SPX data
                    self.connection_manager.tws.cancelMktData(2)  # Cancel ES data
                    self.connection_manager.tws.cancelMktData(3)  # Cancel contract details request
                    self.connection_manager.tws.disconnect()
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