import schedule
import time
from datetime import datetime
import pytz
from typing import Callable, Dict, Any
import logging

class TradeScheduler:
    def __init__(self):
        self.et_timezone = pytz.timezone('US/Eastern')
        self.scheduled_trades: Dict[str, Any] = {}
        self.trades = []
        self.last_run = {}  # Track last run time for each trade
        
    def add_trade(self, trade_name: str, time_et: str, trade_func: Callable, day: str = "Friday", *args, **kwargs):
        """
        Schedule a trade to run at a specific time (ET) on a specific day
        
        Args:
            trade_name: Unique name for this trade
            time_et: Time in ET (24h format) e.g. "14:43"
            trade_func: Function to execute
            day: Day of the week (default: "Friday")
            *args, **kwargs: Arguments to pass to trade_func
        """
        def job():
            print(f"\n🕒 Executing scheduled trade: {trade_name} at {datetime.now(self.et_timezone).strftime('%H:%M:%S ET')}")
            try:
                trade_func(*args, **kwargs)
            except Exception as e:
                print(f"Error executing trade {trade_name}: {str(e)}")
        
        # Schedule the job for the specified day
        if day.lower() == "monday":
            schedule.every().monday.at(time_et).do(job)
        elif day.lower() == "tuesday":
            schedule.every().tuesday.at(time_et).do(job)
        elif day.lower() == "wednesday":
            schedule.every().wednesday.at(time_et).do(job)
        elif day.lower() == "thursday":
            schedule.every().thursday.at(time_et).do(job)
        else:  # Default to Friday
            schedule.every().friday.at(time_et).do(job)
            
        self.scheduled_trades[trade_name] = {
            'time': time_et,
            'day': day,
            'function': trade_func,
            'args': args,
            'kwargs': kwargs
        }
        self.trades.append({
            "name": trade_name,
            "time_et": time_et,
            "func": trade_func,
            "day": day
        })
        self.last_run[trade_name] = None
        print(f"\n📅 Scheduled {trade_name} for {time_et} ET on {day}")
        
    def remove_trade(self, trade_name: str):
        """Remove a scheduled trade"""
        if trade_name in self.scheduled_trades:
            schedule.clear(trade_name)
            del self.scheduled_trades[trade_name]
            self.trades = [t for t in self.trades if t["name"] != trade_name]
            print(f"\nRemoved scheduled trade: {trade_name}")
            
    def list_trades(self):
        """List all scheduled trades"""
        print("\n📋 Scheduled Trades:")
        for name, details in self.scheduled_trades.items():
            print(f"- {name}: {details['time']} ET on {details['day']}")
        print("\nScheduled Trades:")
        print("-" * 50)
        for trade in self.trades:
            print(f"{trade['day']} {trade['time_et']} ET: {trade['name']}")
        print("-" * 50)
            
    def get_next_trade(self):
        """Get the next scheduled trade"""
        if not self.trades:
            return None
            
        et_now = datetime.now(pytz.timezone('US/Eastern'))
        current_day = et_now.strftime('%A')
        current_time = et_now.strftime('%H:%M')
        
        # First, look for trades today
        todays_trades = [t for t in self.trades if t['day'] == current_day]
        future_trades = [t for t in todays_trades if t['time_et'] > current_time]
        
        if future_trades:
            # Return the next trade today
            return min(future_trades, key=lambda x: x['time_et'])
        
        # If no trades left today, find the next day that has trades
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        current_day_idx = days.index(current_day)
        
        for i in range(1, 8):  # Look through next 7 days
            next_day_idx = (current_day_idx + i) % 7
            next_day = days[next_day_idx]
            next_day_trades = [t for t in self.trades if t['day'] == next_day]
            
            if next_day_trades:
                # Return the first trade of the next trading day
                return min(next_day_trades, key=lambda x: x['time_et'])
        
        return None
    
    def run(self):
        """Run the scheduler once"""
        schedule.run_pending() 