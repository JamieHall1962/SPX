import sys
from datetime import datetime
import pytz
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QGridLayout, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer

from trading.manager import TradingManager
from utils.market_utils import is_market_hours
from connection.tws_manager import MarketData

class TradingDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        print("Initializing Dashboard...")  # Debug print
        self.setWindowTitle("SPX Trading Dashboard")
        self.resize(800, 600)
        
        # Create UI elements FIRST
        self.create_ui_elements()
        
        # THEN initialize trading manager and callbacks
        self.trading_manager = TradingManager()
        self.trading_manager.connection_manager.add_status_callback(self.update_status)
        
        # Add callbacks with rate limiting
        self.market_callback_id = self.trading_manager.connection_manager.add_market_callback(
            self.on_market_update
        )
        
        # Setup timer for status updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)  # Update every second
        
        # Setup close handling
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        print("Dashboard initialized")  # Debug print
        
        self.running = False  # Add running flag
        self.trades_tree = None  # Initialize the attribute
        self.status_callback_id = None
    
    def create_ui_elements(self):
        """Create all UI elements"""
        # Status Frame
        status_frame = QGridLayout()
        
        # Connection Status
        self.connection_status = QLabel('Connection: Disconnected')
        self.connection_status.setStyleSheet('font-size: 14px; padding: 5px;')
        
        # Price Labels
        self.spx_price_label = QLabel('SPX: --')
        self.spx_price_label.setStyleSheet('font-size: 14px; padding: 5px;')
        
        self.es_price_label = QLabel('ES: --')
        self.es_price_label.setStyleSheet('font-size: 14px; padding: 5px;')
        
        # Control buttons with styling
        self.start_button = QPushButton('Start Trading')
        self.start_button.setStyleSheet('font-size: 14px; padding: 10px;')
        self.start_button.clicked.connect(self.start_trading)
        
        self.stop_button = QPushButton('Stop Trading')
        self.stop_button.setStyleSheet('font-size: 14px; padding: 10px;')
        self.stop_button.clicked.connect(self.stop_trading)
        self.stop_button.setEnabled(False)
        
        # Add widgets to status layout
        status_frame.addWidget(self.connection_status, 0, 0)
        status_frame.addWidget(self.spx_price_label, 1, 0)
        status_frame.addWidget(self.es_price_label, 1, 1)
        
        # Create main layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(status_frame)
        
        # Create button layout
        button_layout = QGridLayout()
        button_layout.addWidget(self.start_button, 0, 0)
        button_layout.addWidget(self.stop_button, 0, 1)
        
        # Add layouts to main layout
        main_layout.addLayout(button_layout)
        
        # Create central widget and set layout
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        print("UI setup complete")  # Debug print
    
    def start_trading(self):
        """Start trading system"""
        print("Starting trading...")
        if not self.running:
            self.running = True
            self.trading_manager.connection_manager.start()
            self.start_button.setEnabled(False)  # PyQt method
            self.stop_button.setEnabled(True)    # PyQt method
    
    def stop_trading(self):
        """Stop trading system"""
        print("Stopping trading...")
        if self.running:
            self.running = False
            self.trading_manager.connection_manager.stop()
            self.stop_button.setEnabled(False)   # PyQt method
            self.start_button.setEnabled(True)   # PyQt method
    
    def update_status(self, status=None):
        """Handle status updates"""
        if status is None:
            # If called directly without status, get it from trading manager
            try:
                status = self.trading_manager.get_status()
            except Exception as e:
                print(f"Error getting status: {e}")
                return
            
        try:
            if status.get("connected"):
                self.connection_status.setText("Connected")
                self.connection_status.setStyleSheet('font-size: 14px; padding: 5px; color: green;')
            else:
                self.connection_status.setText("Disconnected")
                self.connection_status.setStyleSheet('font-size: 14px; padding: 5px; color: red;')
                
            if status.get("spx_price"):
                self.spx_price_label.setText(f'SPX: {status["spx_price"]}')
            if status.get("es_price"):
                self.es_price_label.setText(f'ES: {status["es_price"]}')
                
        except Exception as e:
            print(f"Error updating status: {e}")
    
    def update_trades_tree(self, active_trades):
        """Update the trades tree widget with current trade status"""
        self.trades_tree.clear()
        for trade_id, trade in active_trades.items():
            item = QTreeWidgetItem(self.trades_tree)
            item.setText(0, trade.entry_time.strftime("%H:%M:%S"))
            item.setText(1, trade_id)
            item.setText(2, self._get_trade_status_text(trade))
    
    def _get_trade_status_text(self, trade):
        """Convert trade status to display text"""
        if "pnl" in trade.current_status:
            return f"P&L: ${trade.current_status['pnl']:.2f}"
        return "Active"
    
    def emergency_stop(self):
        """Stop all trading operations and UI updates"""
        print("Emergency stop initiated...")
        try:
            self.running = False
            self.timer.stop()
            
            if self.trading_manager:
                self.trading_manager.stop()
                self.trading_manager = None
            
            # Reset UI
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.connection_status.setText("❌ DISCONNECTED")
            self.spx_price_label.setText("---.--")
            self.es_price_label.setText("---.--")
            self.trades_tree.clear()
            
        except Exception as e:
            print(f"Error in emergency_stop: {str(e)}")
    
    def closeEvent(self, event):
        """Handle window close event"""
        print("Trading system stopped")
        try:
            if self.trading_manager and self.trading_manager.connection_manager:
                if self.market_callback_id is not None:
                    self.trading_manager.connection_manager.remove_market_callback(
                        self.market_callback_id
                    )
                if self.status_callback_id is not None:
                    self.trading_manager.connection_manager.remove_status_callback(
                        self.status_callback_id
                    )
        except Exception as e:
            print(f"Error during shutdown: {e}")
        event.accept()

    def on_market_update(self, market_data: MarketData):
        """Handle market data updates"""
        if market_data.symbol == "SPX":
            self.spx_price_label.setText(f'SPX: {market_data.price:.2f}')
        elif market_data.symbol == "ES":
            self.es_price_label.setText(f'ES: {market_data.price:.2f}')

def main():
    print("Starting application...")  # Debug print
    app = QApplication(sys.argv)
    window = TradingDashboard()
    window.show()
    print("Window should be visible now")  # Debug print
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 