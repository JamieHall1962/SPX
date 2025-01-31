from dataclasses import dataclass
from typing import Literal

@dataclass
class TradeConfig:
    # Trade type
    trade_type: Literal["IC", "DC"]
    
    # Common parameters
    quantity: int = 1
    
    # DTE parameters
    short_dte: int = 1
    put_long_dte: int = None  # For DC only
    call_long_dte: int = None  # For DC only
    
    # Delta targets
    put_delta: float = 0.15
    call_delta: float = 0.15
    
    # Width/Offset parameters
    put_width: int = 20  # For IC: wing width, For DC: strike offset
    call_width: int = 20  # For IC: wing width, For DC: strike offset
    
    # Price adjustment parameters
    initial_wait: int = 60   # 1 minute
    second_wait: int = 60    # 1 minute
    third_wait: int = 60     # 1 minute
    fourth_wait: int = 60    # 1 minute
    final_wait: int = 60     # 1 minute
    price_increment_pct: float = 0.01  # 1% increment
    
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
    quantity=3,
    short_dte=1,
    put_delta=0.20,
    call_delta=0.06,
    put_width=20,
    call_width=20
)

DC_CONFIG = TradeConfig(
    trade_type="DC",
    quantity=3,
    short_dte=3,
    put_long_dte=6,
    call_long_dte=7,
    put_delta=0.30,
    call_delta=0.35,
    put_width=0,  # offset
    call_width=0  # offset
)

DC_CONFIG_2 = TradeConfig(
    trade_type="DC",
    quantity=5,
    short_dte=5,
    put_long_dte=7,
    call_long_dte=7,
    put_delta=0.50,
    call_delta=0.50,
    put_width=0,  # offset
    call_width=0  # offset
)

DC_CONFIG_3 = TradeConfig(
    trade_type="DC",
    quantity=3,
    short_dte=3,
    put_long_dte=5,
    call_long_dte=5,
    put_delta=0.30,
    call_delta=0.15,
    put_width=25,  # offset
    call_width=25  # offset
)

DC_CONFIG_4 = TradeConfig(
    trade_type="DC",
    quantity=3,
    short_dte=3,
    put_long_dte=7,
    call_long_dte=7,
    put_delta=0.30,
    call_delta=0.20,
    put_width=20,  # offset
    call_width=20  # offset
) 