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

class TradingDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SPX Trading Dashboard")
        self.resize(800, 600)
        
        # Initialize components
        self.trading_manager = None
        self.running = False
        self.start_time = datetime.now()
        
        # Create UI
        self.setup_ui()
        
        # Setup timer for status updates
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        
        # Setup close handling
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    
    def start_trading(self):
        """Start the trading system and UI updates"""
        if not self.running:
            try:
                print("Starting trading system...")
                self.running = True
                
                # Initialize trading manager
                self.trading_manager = TradingManager()
                if not self.trading_manager.start():
                    raise Exception("Failed to start trading system")
                
                # Start UI updates
                self.status_timer.start(1000)
                
                # Update UI
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                
                print("Trading system startup complete")
                
            except Exception as e:
                print(f"Error in start_trading: {str(e)}")
                self.emergency_stop()
    
    def update_status(self):
        """Update all UI elements with current system status"""
        try:
            if not self.running or not self.trading_manager:
                return
            
            # Get status from trading manager
            status = self.trading_manager.get_status()
            
            # Update connection status
            self.connection_status.setText(
                "✅ CONNECTED" if status.is_connected else "❌ DISCONNECTED"
            )
            
            # Update market status
            self.market_hours.setText("Yes" if status.market_open else "No")
            
            # Update prices
            self.spx_price.setText(
                f"{status.spx_price:.2f}" if status.spx_price else "---.--"
            )
            self.es_price.setText(
                f"{status.es_price:.2f}" if status.es_price else "---.--"
            )
            
            # Update next trade
            next_trade = status.next_trade
            if next_trade:
                self.next_trade.setText(
                    f"{next_trade['day']} {next_trade['time']} ET - {next_trade['name']}"
                )
            else:
                self.next_trade.setText("None")
            
            # Update active trades in tree widget
            self.update_trades_tree(status.active_trades)
            
            # Update uptime
            uptime = datetime.now() - self.start_time
            hours = int(uptime.total_seconds() // 3600)
            minutes = int((uptime.total_seconds() % 3600) // 60)
            self.uptime.setText(f"{hours}h {minutes}m")
            
        except Exception as e:
            print(f"Error updating status: {str(e)}")
    
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
            self.status_timer.stop()
            
            if self.trading_manager:
                self.trading_manager.stop()
                self.trading_manager = None
            
            # Reset UI
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.connection_status.setText("❌ DISCONNECTED")
            self.market_hours.setText("No")
            self.spx_price.setText("---.--")
            self.es_price.setText("---.--")
            self.next_trade.setText("None")
            self.uptime.setText("0h 0m")
            self.trades_tree.clear()
            
        except Exception as e:
            print(f"Error in emergency_stop: {str(e)}")
    
    def closeEvent(self, event):
        """Handle application closure"""
        print("Close event received...")
        if self.running:
            self.emergency_stop()
        event.accept()
        print("Close event completed")

    def setup_ui(self):
        """Setup all UI components"""
        # [Your existing UI setup code remains unchanged]
        pass

def main():
    app = QApplication(sys.argv)
    window = TradingDashboard()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 