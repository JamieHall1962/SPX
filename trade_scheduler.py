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
        
    def add_trade(self, trade_name: str, time_et: str, trade_func: Callable, *args, **kwargs):
        """
        Schedule a trade to run at a specific time (ET)
        
        Args:
            trade_name: Unique name for this trade
            time_et: Time in ET (24h format) e.g. "14:43"
            trade_func: Function to execute
            *args, **kwargs: Arguments to pass to trade_func
        """
        def job():
            print(f"\n🕒 Executing scheduled trade: {trade_name} at {datetime.now(self.et_timezone).strftime('%H:%M:%S ET')}")
            try:
                trade_func(*args, **kwargs)
            except Exception as e:
                print(f"Error executing trade {trade_name}: {str(e)}")
        
        # Schedule the job
        schedule.every().day.at(time_et).do(job)
        self.scheduled_trades[trade_name] = {
            'time': time_et,
            'function': trade_func,
            'args': args,
            'kwargs': kwargs
        }
        print(f"\n📅 Scheduled {trade_name} for {time_et} ET")
        
    def remove_trade(self, trade_name: str):
        """Remove a scheduled trade"""
        if trade_name in self.scheduled_trades:
            schedule.clear(trade_name)
            del self.scheduled_trades[trade_name]
            print(f"\nRemoved scheduled trade: {trade_name}")
            
    def list_trades(self):
        """List all scheduled trades"""
        print("\n📋 Scheduled Trades:")
        for name, details in self.scheduled_trades.items():
            print(f"- {name}: {details['time']} ET")
            
    def run(self):
        """Run the scheduler"""
        print("\n⚡ Trade scheduler is running...")
        print("Waiting for scheduled trades...")
        
        while True:
            schedule.run_pending()
            time.sleep(1) 