import schedule
import time
from datetime import datetime
import pytz
from typing import Callable, Dict, Any
import logging
from config.trade_config import (
    TradeConfig, TradeType,
    DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3,
    DC_CONFIG_4, DC_CONFIG_5, DC_CONFIG_6,
    IC_CONFIG
)
from threading import Thread, Event
import traceback

class TradeScheduler:
    def __init__(self, executor):
        print("Initializing TradeScheduler...")
        self.et_timezone = pytz.timezone('US/Eastern')
        self.executor = executor
        self._running = False
        self._stop_event = Event()
        self._thread = None
        self.setup_schedules()
        print("TradeScheduler initialized")

    def setup_schedules(self):
        """Setup all trade schedules"""
        print("Setting up trade schedules...")
        for config in [DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3, 
                      DC_CONFIG_4, DC_CONFIG_5, DC_CONFIG_6, IC_CONFIG]:
            hour, minute = config.entry_time.split(":")
            for day in config.entry_days:
                schedule.every().day.at(config.entry_time).do(
                    self.check_and_execute_trade, config
                ).tag(config.trade_name)
            print(f"Scheduled {config.trade_name} for {config.entry_time} on {config.entry_days}")

    def check_and_execute_trade(self, config: TradeConfig) -> bool:
        """Check conditions and execute trade if met"""
        now = datetime.now(self.et_timezone)
        current_day = now.strftime("%A")
        
        if current_day in config.entry_days and config.active:
            print(f"✨ Entry conditions met for {config.trade_name}")
            if config.trade_type == TradeType.DOUBLE_CALENDAR:
                return self.executor.execute_double_calendar(config)
            elif config.trade_type == TradeType.IRON_CONDOR:
                return self.executor.execute_iron_condor(config)
        return False

    def start(self):
        """Start the scheduler in a separate thread"""
        print("Starting scheduler...")
        self._running = True
        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the scheduler"""
        print("Stopping scheduler...")
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        schedule.clear()

    def _run_loop(self):
        """Main scheduling loop"""
        print("Scheduler loop running...")
        while self._running and not self._stop_event.is_set():
            try:
                schedule.run_pending()
                if not self._running:
                    print("Running flag turned off - stopping scheduler")
                    return
                if self._stop_event.is_set():
                    print("Stop event set - stopping scheduler")
                    return
                
                # Check if TWS is still connected
                if not self.executor.connection_manager.is_connected():
                    print("TWS connection lost - attempting reconnect")
                    self.executor.connection_manager.connect()
                
                if self._stop_event.wait(1):
                    print("Scheduler stop requested during wait")
                    return
                
            except Exception as e:
                print(f"❌ Critical error in scheduler loop: {e}")
                traceback.print_exc()
                print("Attempting to continue...")
                if self._stop_event.wait(1):
                    print("Scheduler stop requested after error")
                    return 