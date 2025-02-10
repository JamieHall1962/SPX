from datetime import datetime, time
import pytz
from typing import Tuple

def get_market_schedule() -> Tuple[time, time]:
    """Get market open and close times"""
    market_open = time(20, 15)  # 8:15 PM ET
    market_close = time(9, 15)  # 9:15 AM ET next day
    return market_open, market_close

def is_market_hours() -> bool:
    """Check if current time is during extended market hours"""
    et_timezone = pytz.timezone('US/Eastern')
    current_time = datetime.now(et_timezone)
    
    market_open, market_close = get_market_schedule()
    current_time_only = current_time.time()
    
    # If we're between 20:15 and 23:59
    if market_open <= current_time_only:
        return True
    # If we're between 00:00 and 09:15
    elif current_time_only <= market_close:
        return True
    
    return False

def is_trading_day() -> bool:
    """Check if today is a trading day"""
    et_timezone = pytz.timezone('US/Eastern')
    current_time = datetime.now(et_timezone)
    
    # Check if it's a weekday (Monday = 0, Sunday = 6)
    if current_time.weekday() in [5, 6]:  # Saturday or Sunday
        return False
        
    # TODO: Add holiday calendar check
    return True

def get_market_status() -> dict:
    """Get detailed market status information"""
    now = datetime.now(pytz.timezone('US/Eastern'))
    
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    is_open = (
        now.weekday() < 5 and  # Weekday
        market_open <= now <= market_close  # During market hours
    )
    
    return {
        'is_open': is_open,
        'current_time': now,
        'market_open_time': market_open,
        'market_close_time': market_close,
        'day_of_week': now.strftime('%A')
    }