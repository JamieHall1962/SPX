# config/trade_config.py
from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from datetime import time

class TradeType(Enum):
    """Types of trades the system can execute"""
    IRON_CONDOR = auto()
    DOUBLE_CALENDAR = auto()
    PUT_BUTTERFLY = auto()
    CALL_BUTTERFLY = auto()
    VERTICAL_SPREAD = auto()

class MarketCondition(Enum):
    """Market condition classifications"""
    BULLISH = auto()
    BEARISH = auto()
    NEUTRAL = auto()
    VOLATILE = auto()
    LOW_VOLATILITY = auto()

@dataclass
class TradeConfig:
    """Base configuration for a trade strategy"""
    name: str
    trade_type: TradeType
    active: bool = True
    
    # Entry conditions
    entry_days: List[int] = None  # 0 = Monday, 4 = Friday
    entry_time: time = None
    max_daily_trades: int = 1
    
    # Exit conditions
    profit_target_percent: float = None
    stop_loss_percent: float = None
    max_hold_days: int = None
    exit_time: time = None

@dataclass
class IronCondorConfig(TradeConfig):
    """Configuration for Iron Condor strategy"""
    # Entry parameters
    put_delta: float = 0.16       # Target delta for short put
    call_delta: float = 0.16      # Target delta for short call
    wing_width: int = 20          # Distance to long options in points
    
    # Exit parameters
    max_delta: float = 0.25       # Exit if short leg delta exceeds this
    tested_leg_adjustment: bool = True  # Adjust tested legs
    
    def __post_init__(self):
        self.trade_type = TradeType.IRON_CONDOR

@dataclass
class DoubleCalendarConfig(TradeConfig):
    """Configuration for Double Calendar strategy"""
    # Entry parameters
    short_dte: int = 1            # DTE for short options
    long_dte: int = 8             # DTE for long options
    put_delta: float = 0.30       # Target delta for put legs
    call_delta: float = 0.30      # Target delta for call legs
    
    # Exit parameters
    max_iv_increase: float = 0.10  # Exit if IV increases by this amount
    time_decay_threshold: float = 0.30  # Exit when time decay reaches this point
    
    def __post_init__(self):
        self.trade_type = TradeType.DOUBLE_CALENDAR

@dataclass
class PutButterflyConfig(TradeConfig):
    """Configuration for Put Butterfly strategy"""
    # Entry parameters
    dte: int = 1                  # DTE for all options
    center_delta: float = 0.30    # Target delta for center strike
    wing_width: int = 20          # Distance to wing strikes in points
    
    # Exit parameters
    profit_target_percent: float = 0.15  # Default profit target
    stop_loss_percent: float = 0.50      # Default stop loss
    
    def __post_init__(self):
        self.trade_type = TradeType.PUT_BUTTERFLY

# Sample Trade Strategy Configurations

# Weekday Iron Condor
weekday_ic = IronCondorConfig(
    name="Weekday SPX Iron Condor",
    entry_days=[0, 1, 2, 3],  # Monday through Thursday
    entry_time=time(10, 0),   # 10:00 AM ET
    put_delta=0.16,
    call_delta=0.10,
    wing_width=20,
    max_delta=0.25,
    profit_target_percent=0.25,
    stop_loss_percent=0.70,
    max_hold_days=1,
    exit_time=time(15, 30)    # 3:30 PM ET
)

# Monday Double Calendar
monday_dc = DoubleCalendarConfig(
    name="Monday SPX Double Calendar",
    entry_days=[0],           # Monday only
    entry_time=time(10, 30),  # 10:30 AM ET
    short_dte=1,
    long_dte=8,
    put_delta=0.30,
    call_delta=0.30,
    profit_target_percent=0.20,
    stop_loss_percent=0.40,
    max_hold_days=3
)

# Friday Put Butterfly
friday_butterfly = PutButterflyConfig(
    name="Friday SPX Put Butterfly",
    entry_days=[4],           # Friday only
    entry_time=time(9, 45),   # 9:45 AM ET
    dte=1,
    center_delta=0.30,
    wing_width=20,
    profit_target_percent=0.18,
    stop_loss_percent=0.50,
    exit_time=time(15, 0)     # 3:00 PM ET
)

# Active strategy configurations
active_strategies = [
    weekday_ic,
    monday_dc,
    friday_butterfly
]
