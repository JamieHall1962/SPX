from dataclasses import dataclass
from typing import Literal, Callable

@dataclass
class TradeConfig:
    # Required parameters
    trade_type: Literal["IC", "DC"]
    put_delta: Callable[[], float]  # Function that returns target delta or premium
    call_delta: Callable[[], float]  # Function that returns target delta or premium
    
    # Optional parameters with defaults
    quantity: int = 1
    short_dte: int = 1
    put_long_dte: int = None  # For DC only
    call_long_dte: int = None  # For DC only
    put_width: int = 20  # For IC: wing width, For DC: strike offset
    call_width: int = 20  # For IC: wing width, For DC: strike offset
    initial_wait: int = 60   # 1 minute
    second_wait: int = 60    # 1 minute
    third_wait: int = 60     # 1 minute
    fourth_wait: int = 60    # 1 minute
    final_wait: int = 60     # 1 minute
    price_increment_pct: float = 0.01  # 1% increment
    
    def __post_init__(self):
        # Convert put_delta and call_delta to numeric values if they are callable
        if callable(self.put_delta):
            self.put_delta = self.put_delta()
        if callable(self.call_delta):
            self.call_delta = self.call_delta()

    @property
    def trade_name(self) -> str:
        """Generate trade name based on parameters"""
        if self.trade_type == "IC":
            # Format: IC_1D_2006_20
            put_delta_str = f"{abs(self.put_delta * 100):02.0f}"
            call_delta_str = f"{abs(self.call_delta * 100):02.0f}"
            return f"IC_{self.short_dte}D_{put_delta_str}{call_delta_str}_{self.put_width}"
        else:  # DC
            # Format: DC_3D_67D_3035_0
            put_delta_str = f"{abs(self.put_delta * 100):02.0f}"
            call_delta_str = f"{abs(self.call_delta * 100):02.0f}"
            return f"DC_{self.short_dte}D_{self.put_long_dte}{self.call_long_dte}D_{put_delta_str}{call_delta_str}_{self.put_width}"

# Example configurations
IC_CONFIG = TradeConfig(
    trade_type="IC",
    put_delta=lambda: 0.20,
    call_delta=lambda: 0.06,
    quantity=3,
    short_dte=1,
    put_width=20,
    call_width=20
)

DC_CONFIG = TradeConfig(
    trade_type="DC",
    put_delta=lambda: 0.30,
    call_delta=lambda: 0.35,
    quantity=3,
    short_dte=3,
    put_long_dte=6,
    call_long_dte=7,
    put_width=0,  # offset
    call_width=0  # offset
)

DC_CONFIG_2 = TradeConfig(
    trade_type="DC",
    put_delta=lambda: 0.50,
    call_delta=lambda: 0.50,
    quantity=5,
    short_dte=5,
    put_long_dte=7,
    call_long_dte=7,
    put_width=0,  # offset
    call_width=0  # offset
)

DC_CONFIG_3 = TradeConfig(
    trade_type="DC",
    put_delta=lambda: 0.30,
    call_delta=lambda: 0.15,
    quantity=3,
    short_dte=3,
    put_long_dte=5,
    call_long_dte=5,
    put_width=25,  # offset
    call_width=25  # offset
)

DC_CONFIG_4 = TradeConfig(
    trade_type="DC",
    put_delta=lambda: 0.30,
    call_delta=lambda: 0.20,
    quantity=3,
    short_dte=3,
    put_long_dte=7,
    call_long_dte=7,
    put_width=20,  # offset
    call_width=20  # offset
)

DC_CONFIG_5 = TradeConfig(
    trade_type="DC",
    put_delta=lambda: 0.12,
    call_delta=lambda: 0.17,
    quantity=3,
    short_dte=3,
    put_long_dte=7,
    call_long_dte=7,
    put_width=0,  # offset
    call_width=0  # offset
)

DC_CONFIG_6 = TradeConfig(
    trade_type="DC",
    put_delta=lambda: 0.25,
    call_delta=lambda: 0.25,
    quantity=3,
    short_dte=1,
    put_long_dte=4,
    call_long_dte=4,
    put_width=0,  # offset
    call_width=0  # offset
)

# Function to return premium values
def get_put_premium():
    return 1.60

def get_call_premium():
    return 1.30

# Custom 0DTE Strangle Config
CUSTOM_STRANGLE_CONFIG = TradeConfig(
    trade_type="DC",
    put_delta=get_put_premium,  # Use the actual function, not lambda
    call_delta=get_call_premium,  # Use the actual function, not lambda
    quantity=1,
    short_dte=0,
    put_long_dte=0,
    call_long_dte=0,
    put_width=30,
    call_width=30,
    initial_wait=60,
    second_wait=60,
    third_wait=60,
    price_increment_pct=0.05
) 