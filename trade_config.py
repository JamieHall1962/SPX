from dataclasses import dataclass
from typing import List, Dict, Union, Optional
from enum import Enum
from datetime import time

class TradeType(Enum):
    """Available trade types in the system"""
    DOUBLE_CALENDAR = "double_calendar"
    PUT_FLY = "put_fly"
    IRON_CONDOR = "iron_condor"
    CUSTOM_STRANGLE = "custom_strangle"
    HEDGE = "hedge"

class MarketCondition(Enum):
    """Market conditions required for entry"""
    ANY = "any"
    UP = "up"
    DOWN = "down"
    FLAT = "flat"

class ExitTimeReference(Enum):
    """Reference point for exit times"""
    SHORT_EXPIRY = "short_expiry"  # Exit relative to short option expiration
    ENTRY_DAY = "entry_day"        # Exit relative to entry day
    SPECIFIC_DATE = "specific_date" # Exit on specific date
    LONG_EXPIRY = "long_expiry"    # Exit relative to long option expiration

@dataclass
class ExitTime:
    """
    Specification for time-based exits
    
    Parameters:
        time: Exit time in "HH:MM" format (ET)
        reference: Which day to reference for exit
        specific_date: Only used if reference is SPECIFIC_DATE
    """
    time: str
    reference: ExitTimeReference = ExitTimeReference.SHORT_EXPIRY
    specific_date: Optional[str] = None  # "YYYY-MM-DD" format if needed

@dataclass
class LegConfig:
    """
    Configuration for a single option leg
    
    Parameters:
        leg_type: "PUT" or "CALL"
        dte: Days to expiration for this leg
        position: 1 for long, -1 for short
        quantity: Relative quantity (will be multiplied by trade quantity)
        delta_target: Target delta for short legs (None for long legs)
        strike_offset: Strike distance from short leg (0 for same strike)
    """
    leg_type: str
    dte: int
    position: int
    quantity: int
    delta_target: Optional[float] = None
    strike_offset: int = 0

@dataclass
class TradeConfig:
    """
    Master configuration for a specific trade strategy
    
    Parameters:
        trade_name: Unique identifier for this strategy
        trade_type: Type of trade (e.g., DOUBLE_CALENDAR)
        entry_time: Entry time in "HH:MM" format (ET)
        entry_days: List of valid entry days
        legs: List of option legs configurations
        market_condition: Required market condition for entry
        max_debit: Maximum debit allowed for entry
        min_credit: Minimum credit required (for credit trades)
        exit_conditions: Dictionary of exit triggers
        time_based_exits: List of exit times
        active: Whether this trade is currently active
        description: Detailed description of the strategy
    """
    trade_name: str
    trade_type: TradeType
    entry_time: str
    entry_days: List[str]
    legs: List[LegConfig]
    market_condition: MarketCondition
    max_debit: Optional[float] = None
    min_credit: Optional[float] = None
    exit_conditions: Dict[str, Union[float, str]]
    time_based_exits: List[ExitTime]
    active: bool = True
    description: str = ""

# Double Calendar Configurations
DC_CONFIG = TradeConfig(
    # Basic identification
    trade_name="DC_Friday_1015",
    trade_type=TradeType.DOUBLE_CALENDAR,
    
    # Entry parameters
    entry_time="10:15",
    entry_days=["Friday"],
    market_condition=MarketCondition.ANY,
    
    # Leg definitions
    legs=[
        LegConfig(
            leg_type="PUT",
            dte=6,
            position=1,
            quantity=1,
            strike_offset=0  # 0-point wing
        ),
        LegConfig(
            leg_type="PUT",
            dte=3,
            position=-1,
            quantity=1,
            delta_target=0.30  # 30▲
        ),
        LegConfig(
            leg_type="CALL",
            dte=7,
            position=1,
            quantity=1,
            strike_offset=0  # 0-point wing
        ),
        LegConfig(
            leg_type="CALL",
            dte=3,
            position=-1,
            quantity=1,
            delta_target=0.35  # 35▲
        )
    ],
    
    # Risk parameters
    max_debit=100.00,
    min_credit=None,
    
    # Exit conditions
    exit_conditions={
        "abs_delta_threshold": 70
    },
    
    # Time-based exits
    time_based_exits=[
        ExitTime(
            time="13:05",
            reference=ExitTimeReference.SHORT_EXPIRY  # Exits Monday at 13:05 ET
        )
    ],
    
    description="""
    Double Calendar entered Friday 10:15 ET
    - Short legs: 3 DTE (30▲ put, 35▲ call)
    - Long legs: 6/7 DTE with 0-point wings
    - Entry: Max debit $100.00
    - Exits:
      • ABS(Delta) > 70
      • Monday at 13:05 ET
    """
)

DC_CONFIG_2 = TradeConfig(
    # Basic identification
    trade_name="DC_Friday_1155",
    trade_type=TradeType.DOUBLE_CALENDAR,
    
    # Entry parameters
    entry_time="11:55",
    entry_days=["Friday"],
    market_condition=MarketCondition.ANY,
    
    # Leg definitions
    legs=[
        LegConfig(
            leg_type="PUT",
            dte=7,
            position=1,
            quantity=1,
            strike_offset=0  # 0-point wing
        ),
        LegConfig(
            leg_type="PUT",
            dte=5,
            position=-1,
            quantity=1,
            delta_target=0.50  # 50▲
        ),
        LegConfig(
            leg_type="CALL",
            dte=7,
            position=1,
            quantity=1,
            strike_offset=0  # 0-point wing
        ),
        LegConfig(
            leg_type="CALL",
            dte=5,
            position=-1,
            quantity=1,
            delta_target=0.50  # 50▲
        )
    ],
    
    # Risk parameters
    max_debit=100.00,
    min_credit=None,
    
    # Exit conditions
    exit_conditions={
        "abs_delta_threshold": 17.5
    },
    
    # Time-based exits
    time_based_exits=[
        ExitTime(
            time="13:55",
            reference=ExitTimeReference.SHORT_EXPIRY  # Exits Wednesday at 13:55 ET
        )
    ],
    
    description="""
    Double Calendar entered Friday 11:55 ET
    - Short legs: 5 DTE (50▲ put, 50▲ call)
    - Long legs: 7 DTE with 0-point wings
    - Entry: Max debit $100.00
    - Exits:
      • ABS(Delta) > 17.5
      • Wednesday at 13:55 ET
    """
)

DC_CONFIG_3 = TradeConfig(
    # Basic identification
    trade_name="DC_Friday_1300",
    trade_type=TradeType.DOUBLE_CALENDAR,
    
    # Entry parameters
    entry_time="13:00",
    entry_days=["Friday"],
    market_condition=MarketCondition.ANY,
    
    # Leg definitions
    legs=[
        LegConfig(
            leg_type="PUT",
            dte=5,
            position=1,
            quantity=1,
            strike_offset=25  # 25-point wing
        ),
        LegConfig(
            leg_type="PUT",
            dte=3,
            position=-1,
            quantity=1,
            delta_target=0.30  # 30▲
        ),
        LegConfig(
            leg_type="CALL",
            dte=5,
            position=1,
            quantity=1,
            strike_offset=25  # 25-point wing
        ),
        LegConfig(
            leg_type="CALL",
            dte=3,
            position=-1,
            quantity=1,
            delta_target=0.15  # 15▲
        )
    ],
    
    # Risk parameters
    max_debit=100.00,
    min_credit=None,
    
    # Exit conditions
    exit_conditions={},  # No delta threshold exit
    
    # Time-based exits
    time_based_exits=[
        ExitTime(
            time="14:00",
            reference=ExitTimeReference.SHORT_EXPIRY  # Exits Monday at 14:00 ET
        )
    ],
    
    description="""
    Double Calendar entered Friday 13:00 ET
    - Short legs: 3 DTE (30▲ put, 15▲ call)
    - Long legs: 5 DTE with 25-point wings
    - Entry: Max debit $100.00
    - Exits:
      • Monday at 14:00 ET
    """
)

DC_CONFIG_4 = TradeConfig(
    # Basic identification
    trade_name="DC_Friday_1410",
    trade_type=TradeType.DOUBLE_CALENDAR,
    
    # Entry parameters
    entry_time="14:10",
    entry_days=["Friday"],
    market_condition=MarketCondition.ANY,
    
    # Leg definitions
    legs=[
        LegConfig(
            leg_type="PUT",
            dte=7,
            position=1,
            quantity=1,
            strike_offset=20  # 20-point wing
        ),
        LegConfig(
            leg_type="PUT",
            dte=3,
            position=-1,
            quantity=1,
            delta_target=0.30  # 30▲
        ),
        LegConfig(
            leg_type="CALL",
            dte=7,
            position=1,
            quantity=1,
            strike_offset=20  # 20-point wing
        ),
        LegConfig(
            leg_type="CALL",
            dte=3,
            position=-1,
            quantity=1,
            delta_target=0.20  # 20▲
        )
    ],
    
    # Risk parameters
    max_debit=100.00,
    min_credit=None,
    
    # Exit conditions
    exit_conditions={
        "profit_target": 4.00
    },
    
    # Time-based exits
    time_based_exits=[
        ExitTime(
            time="14:45",
            reference=ExitTimeReference.SHORT_EXPIRY  # Exits Monday at 14:45 ET
        )
    ],
    
    description="""
    Double Calendar entered Friday 14:10 ET
    - Short legs: 3 DTE (30▲ put, 20▲ call)
    - Long legs: 7 DTE with 20-point wings
    - Entry: Max debit $100.00
    - Exits:
      • Profit target $4.00
      • Monday at 14:45 ET
    """
)

DC_CONFIG_5 = TradeConfig(
    # Basic identification
    trade_name="DC_Monday_1200",
    trade_type=TradeType.DOUBLE_CALENDAR,
    
    # Entry parameters
    entry_time="12:00",
    entry_days=["Monday"],
    market_condition=MarketCondition.ANY,
    
    # Leg definitions
    legs=[
        LegConfig(
            leg_type="PUT",
            dte=7,
            position=1,
            quantity=1,
            strike_offset=0  # 0-point wing
        ),
        LegConfig(
            leg_type="PUT",
            dte=3,
            position=-1,
            quantity=1,
            delta_target=0.12  # 12▲
        ),
        LegConfig(
            leg_type="CALL",
            dte=7,
            position=1,
            quantity=1,
            strike_offset=0  # 0-point wing
        ),
        LegConfig(
            leg_type="CALL",
            dte=3,
            position=-1,
            quantity=1,
            delta_target=0.17  # 17▲
        )
    ],
    
    # Risk parameters
    max_debit=100.00,
    min_credit=None,
    
    # Exit conditions
    exit_conditions={
        "profit_target_pct": 0.45,
        "abs_delta_threshold": 11
    },
    
    # Time-based exits
    time_based_exits=[
        ExitTime(
            time="09:45",
            reference=ExitTimeReference.SHORT_EXPIRY  # Exits Thursday at 09:45 ET
        )
    ],
    
    description="""
    Double Calendar entered Monday 12:00 ET
    - Short legs: 3 DTE (12▲ put, 17▲ call)
    - Long legs: 7 DTE with 0-point wings
    - Entry: Max debit $100.00
    - Exits:
      • 45% profit target
      • ABS(Delta) > 11
      • Thursday at 09:45 ET
    """
)

DC_CONFIG_6 = TradeConfig(
    # Basic identification
    trade_name="DC_Monday_1330",
    trade_type=TradeType.DOUBLE_CALENDAR,
    
    # Entry parameters
    entry_time="13:30",
    entry_days=["Monday"],
    market_condition=MarketCondition.ANY,
    
    # Leg definitions
    legs=[
        LegConfig(
            leg_type="PUT",
            dte=4,
            position=1,
            quantity=1,
            strike_offset=0  # 0-point wing
        ),
        LegConfig(
            leg_type="PUT",
            dte=1,
            position=-1,
            quantity=1,
            delta_target=0.25  # 25▲
        ),
        LegConfig(
            leg_type="CALL",
            dte=4,
            position=1,
            quantity=1,
            strike_offset=0  # 0-point wing
        ),
        LegConfig(
            leg_type="CALL",
            dte=1,
            position=-1,
            quantity=1,
            delta_target=0.25  # 25▲
        )
    ],
    
    # Risk parameters
    max_debit=100.00,
    min_credit=None,
    
    # Exit conditions
    exit_conditions={
        "abs_delta_threshold": 30
    },
    
    # Time-based exits
    time_based_exits=[
        ExitTime(
            time="14:45",
            reference=ExitTimeReference.SHORT_EXPIRY  # Exits Tuesday at 14:45 ET
        )
    ],
    
    description="""
    Double Calendar entered Monday 13:30 ET
    - Short legs: 1 DTE (25▲ put, 25▲ call)
    - Long legs: 4 DTE with 0-point wings
    - Entry: Max debit $100.00
    - Exits:
      • ABS(Delta) > 30
      • Tuesday at 14:45 ET
    """
)

IC_CONFIG = TradeConfig(
    # Basic identification
    trade_name="IC_Thursday_1545",
    trade_type=TradeType.IRON_CONDOR,
    
    # Entry parameters
    entry_time="15:45",
    entry_days=["Thursday"],
    market_condition=MarketCondition.ANY,
    
    # Leg definitions
    legs=[
        LegConfig(
            leg_type="PUT",
            dte=1,
            position=1,
            quantity=1,
            strike_offset=-20  # 20 points below short put
        ),
        LegConfig(
            leg_type="PUT",
            dte=1,
            position=-1,
            quantity=1,
            delta_target=0.20  # 20▲
        ),
        LegConfig(
            leg_type="CALL",
            dte=1,
            position=-1,
            quantity=1,
            delta_target=0.06  # 6▲
        ),
        LegConfig(
            leg_type="CALL",
            dte=1,
            position=1,
            quantity=1,
            strike_offset=20  # 20 points above short call
        )
    ],
    
    # Risk parameters
    max_debit=None,
    min_credit=1.80,
    
    # Exit conditions
    exit_conditions={
        "leg_test_threshold": 2.0,  # Exit if SPX within 2 points of any short strike
        "exit_tested_side": True    # Indicates to exit both legs on tested side
    },
    
    # Time-based exits
    time_based_exits=[],  # No timed exits - let untested sides expire at 16:00
    
    description="""
    Iron Condor entered Thursday 15:45 ET
    - Short legs: 1 DTE (20▲ put, 6▲ call)
    - Long legs: 1 DTE with 20-point wings
    - Entry: Min credit $1.80
    - Exits:
      • Exit tested side if SPX within 2 points of short strike
      • Let untested sides expire at 16:00
    """
) 