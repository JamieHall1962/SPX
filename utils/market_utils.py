from datetime import datetime
import pytz

def is_market_hours() -> bool:
    """Check if the US market is currently open"""
    now = datetime.now(pytz.timezone('US/Eastern'))
    
    # Check if it's a weekday
    if now.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    
    # Check if it's during market hours (9:30 AM - 4:00 PM ET)
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return market_open <= now <= market_close

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