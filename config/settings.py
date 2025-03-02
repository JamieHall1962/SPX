# config/settings.py
import os
from pathlib import Path
from datetime import time

# Base directory for the project
BASE_DIR = Path(__file__).resolve().parent.parent

# TWS Connection Settings
TWS_HOST = "127.0.0.1"  # TWS/IB Gateway host
TWS_PORT = 7496         # TWS port (7496 for TWS, 4002 for IB Gateway on paper)
TWS_CLIENT_ID = 1       # Client ID for TWS connection

# Reconnection settings
TWS_MAX_RECONNECT_ATTEMPTS = 5
TWS_RECONNECT_INTERVAL = 10  # seconds

# Market Data Settings
MARKET_DATA_TYPE = 1  # 1 = Live, 2 = Frozen, 3 = Delayed, 4 = Delayed frozen

# Trading Settings
DEFAULT_EXCHANGE = "CBOE"
DEFAULT_CURRENCY = "USD"
TRADING_ACTIVE = True  # Global switch to enable/disable trading

# Trading Hours (ET)
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
MARKET_EARLY_CLOSE = time(13, 0)  # Early close times

# Logging Settings
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_TO_CONSOLE = True
LOG_TO_FILE = True
LOG_ROTATION = "midnight"  # or 'h' (hourly)
LOG_RETENTION = 14  # days

# Notification Settings
ENABLE_TEXT_NOTIFICATIONS = True
TEXT_NOTIFICATION_NUMBER = "+1234567890"  # Replace with your number
ENABLE_EMAIL_NOTIFICATIONS = True
EMAIL_NOTIFICATION_ADDRESS = "your.email@example.com"  # Replace with your email

# Debugging
DEBUG_MODE = True
SANDBOX_MODE = True  # When True, no real orders are placed
