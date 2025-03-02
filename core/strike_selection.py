# core/strike_selection.py
import logging
import bisect
import datetime
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

from utils.logging_utils import setup_logger

# Set up logger
logger = setup_logger("strike_selection")

class OptionData:
    """
    Class to hold option data
    """
    def __init__(self, symbol: str, expiry: str, strike: float, option_type: str,
                 bid: float = 0.0, ask: float = 0.0, last: float = 0.0,
                 volume: int = 0, open_interest: int = 0,
                 delta: float = 0.0, gamma: float = 0.0, theta: float = 0.0,
                 vega: float = 0.0, iv: float = 0.0):
        """
        Initialize option data
        
        Args:
            symbol: Option symbol
            expiry: Option expiration date
            strike: Strike price
            option_type: Option type (C or P)
            bid: Bid price
            ask: Ask price
            last: Last price
            volume: Volume
            open_interest: Open interest
            delta: Delta
            gamma: Gamma
            theta: Theta
            vega: Vega
            iv: Implied volatility
        """
        self.symbol = symbol
        self.expiry = expiry
        self.strike = strike
        self.option_type = option_type
        self.bid = bid
        self.ask = ask
        self.last = last
        self.volume = volume
        self.open_interest = open_interest
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega
        self.iv = iv
        self.mid_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
    
    @property
    def abs_delta(self) -> float:
        """Get absolute delta value"""
        return abs(self.delta)
    
    def __str__(self) -> str:
        """String representation"""
        return (f"{self.symbol} {self.expiry} {self.strike} {self.option_type} "
                f"Bid: {self.bid:.2f} Ask: {self.ask:.2f} Delta: {self.delta:.3f}")


class StrikeSelector:
    """
    Class for selecting option strikes based on various criteria
    """
    def __init__(self, tws_connector=None):
        """
        Initialize the strike selector
        
        Args:
            tws_connector: TWS connector for getting market data
        """
        self.tws_connector = tws_connector
        self.logger = logging.getLogger("strike_selector")
        # Initialize with default logger if not already configured
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def get_expiry_date(self, dte: int) -> str:
        """
        Get the expiry date for a given DTE
        
        Args:
            dte: Days to expiration
            
        Returns:
            str: Expiry date in YYYYMMDD format
        """
        # Simple calculation for expiry date (doesn't account for holidays)
        today = datetime.date.today()
        expiry = today + datetime.timedelta(days=dte)
        return expiry.strftime("%Y%m%d")
    
    def get_option_chain(self, symbol: str, expiry: str) -> List[OptionData]:
        """
        Get the option chain for a given symbol and expiry
        
        Args:
            symbol: Underlying symbol (e.g., "SPX")
            expiry: Option expiration date (format: YYYYMMDD)
            
        Returns:
            List[OptionData]: List of option data
        """
        # This is a placeholder - in the real implementation
        # this would request option chain data from TWS
        # For now, we'll return a mock option chain for testing
        
        logger.info(f"Requesting option chain for {symbol} {expiry}")
        
        # In real implementation, this would use the TWS API to get the option chain
        # return self.tws.request_option_chain(symbol, expiry)
        
        # For now, just return an empty list
        # This will be implemented later
        return []
    
    def find_strike_by_delta(self, option_chain: List[OptionData], target_delta: float, 
                           option_type: str) -> Optional[OptionData]:
        """
        Find the option with delta closest to target delta
        
        Args:
            option_chain: List of option data
            target_delta: Target delta (positive value)
            option_type: "C" for call, "P" for put
            
        Returns:
            OptionData: Option with the closest delta or None if not found
        """
        if not option_chain:
            logger.warning("Empty option chain, cannot find strike by delta")
            return None
        
        # Ensure target_delta is positive
        target_delta = abs(target_delta)
        
        # Filter options by type
        filtered_options = [opt for opt in option_chain if opt.option_type == option_type]
        
        if not filtered_options:
            logger.warning(f"No {option_type} options found in option chain")
            return None
        
        # For puts, we want to find the closest negative delta
        if option_type == "P":
            # Find the option with delta closest to -target_delta
            closest_option = min(filtered_options, 
                                key=lambda opt: abs(abs(opt.delta) - target_delta))
        else:
            # For calls, find the option with delta closest to target_delta
            closest_option = min(filtered_options, 
                                key=lambda opt: abs(opt.delta - target_delta))
        
        logger.info(f"Found strike by delta {target_delta}: {closest_option}")
        return closest_option
    
    def find_strike_by_offset(self, option_chain: List[OptionData], current_strike: float, offset: float, option_type: str) -> Optional[OptionData]:
        """
        Find a strike by offset from current strike
        
        Args:
            option_chain: Option chain data
            current_strike: Current strike price
            offset: Offset amount (can be positive or negative)
            option_type: Option type ("C" or "P")
            
        Returns:
            OptionData: Option data for the selected strike, or None if not found
        """
        target_strike = current_strike + offset
        
        # Round target to nearest 5 since SPX strikes are in 5-point increments
        target_strike = round(target_strike / 5) * 5
        
        # Filter options by type
        filtered_options = [option for option in option_chain if option.option_type == option_type]
        
        if not filtered_options:
            self.logger.warning(f"No options found with type {option_type}")
            return None
        
        # Get all available strikes
        available_strikes = sorted(set(option.strike for option in filtered_options))
        
        if not available_strikes:
            self.logger.warning("No strikes available")
            return None
        
        # Check strike range
        min_strike = min(available_strikes)
        max_strike = max(available_strikes)
        
        # Log available strike range to help diagnose issues
        self.logger.info(f"Available strikes range from {min_strike} to {max_strike} (looking for {target_strike})")
        
        # Calculate direction of offset
        is_higher = offset > 0
        
        # Find closest strike
        if is_higher:
            # Want a higher strike
            if target_strike > max_strike:
                # Target is beyond our range, use the highest available
                self.logger.warning(f"Target strike {target_strike} is beyond max strike {max_strike}, using max")
                closest_strike = max_strike
            else:
                # Find closest available strike above or equal to target
                candidates = [s for s in available_strikes if s >= target_strike]
                closest_strike = min(candidates) if candidates else max_strike
        else:
            # Want a lower strike
            if target_strike < min_strike:
                # Target is beyond our range, use the lowest available
                self.logger.warning(f"Target strike {target_strike} is below min strike {min_strike}, using min")
                closest_strike = min_strike
            else:
                # Find closest available strike below or equal to target
                candidates = [s for s in available_strikes if s <= target_strike]
                closest_strike = max(candidates) if candidates else min_strike
        
        # Find the option with the selected strike
        selected_options = [option for option in filtered_options if abs(option.strike - closest_strike) < 0.01]
        if not selected_options:
            self.logger.warning(f"No option found with strike {closest_strike}")
            return None
        
        selected_option = selected_options[0]
        self.logger.info(f"Selected {option_type} option with strike {selected_option.strike} (target was {target_strike}): delta {selected_option.delta:.3f}")
        
        return selected_option
    
    def select_strikes_for_iron_condor(
        self, 
        symbol: str, 
        dte: int, 
        put_delta: float, 
        call_delta: float, 
        wing_width: int
    ) -> Dict[str, OptionData]:
        """
        Select strikes for an iron condor strategy
        
        Args:
            symbol: Underlying symbol (e.g., "SPX")
            dte: DTE for all options
            put_delta: Target delta for short put (positive value)
            call_delta: Target delta for short call (positive value)
            wing_width: Strike width for wings in points
            
        Returns:
            Dict[str, OptionData]: Selected option data keyed by leg name
        """
        # Calculate expiry date
        expiry = self.get_expiry_date(dte)
        
        logger.info(f"Selecting strikes for iron condor: {symbol} "
                   f"DTE: {dte} (expiry: {expiry}), "
                   f"Put delta: {put_delta}, Call delta: {call_delta}, "
                   f"Wing width: {wing_width}")
        
        # Get option chain
        option_chain = self.get_option_chain(symbol, expiry)
        
        if not option_chain:
            logger.error("Failed to get option chain")
            return {}
        
        # Select short put based on delta
        short_put = self.find_strike_by_delta(option_chain, put_delta, "P")
        
        # Select short call based on delta
        short_call = self.find_strike_by_delta(option_chain, call_delta, "C")
        
        if not short_put or not short_call:
            logger.error("Failed to select short legs")
            return {}
        
        # Select long options based on wing width
        long_put = self.find_strike_by_offset(option_chain, short_put.strike, -wing_width, "P")
        long_call = self.find_strike_by_offset(option_chain, short_call.strike, wing_width, "C")
        
        if not long_put or not long_call:
            logger.error("Failed to select long legs")
            return {}
        
        # Return selected strikes
        return {
            "short_put": short_put,
            "long_put": long_put,
            "short_call": short_call,
            "long_call": long_call
        }
    
    def select_strikes_for_double_calendar(
        self, 
        symbol: str, 
        short_dte: int, 
        long_dte: int,
        put_delta: float, 
        call_delta: float, 
        wing_width: int
    ) -> Dict[str, OptionData]:
        """
        Select strikes for a double calendar strategy
        
        Args:
            symbol: Underlying symbol (e.g., "SPX")
            short_dte: DTE for short options
            long_dte: DTE for long options
            put_delta: Target delta for put legs (positive value)
            call_delta: Target delta for call legs (positive value)
            wing_width: Strike width for additional legs in points
            
        Returns:
            Dict[str, OptionData]: Selected option data keyed by leg name
        """
        # Calculate expiry dates
        short_expiry = self.get_expiry_date(short_dte)
        long_expiry = self.get_expiry_date(long_dte)
        
        logger.info(f"Selecting strikes for double calendar: {symbol} "
                   f"Short DTE: {short_dte} (expiry: {short_expiry}), "
                   f"Long DTE: {long_dte} (expiry: {long_expiry}), "
                   f"Put delta: {put_delta}, Call delta: {call_delta}, "
                   f"Wing width: {wing_width}")
        
        # Get option chains
        short_option_chain = self.get_option_chain(symbol, short_expiry)
        long_option_chain = self.get_option_chain(symbol, long_expiry)
        
        if not short_option_chain or not long_option_chain:
            logger.error("Failed to get option chains")
            return {}
        
        # Select short put based on delta
        short_put = self.find_strike_by_delta(short_option_chain, put_delta, "P")
        
        # Select short call based on delta
        short_call = self.find_strike_by_delta(short_option_chain, call_delta, "C")
        
        if not short_put or not short_call:
            logger.error("Failed to select short legs")
            return {}
        
        # Select long options at the same strikes but different expiry
        long_put = next((opt for opt in long_option_chain 
                        if opt.option_type == "P" and abs(opt.strike - short_put.strike) < 0.01), None)
        
        long_call = next((opt for opt in long_option_chain 
                        if opt.option_type == "C" and abs(opt.strike - short_call.strike) < 0.01), None)
        
        if not long_put or not long_call:
            logger.error("Failed to select long legs")
            return {}
        
        # Return selected strikes
        return {
            "short_put": short_put,
            "long_put": long_put,
            "short_call": short_call,
            "long_call": long_call
        }
    
    def select_strikes_for_put_fly(
        self, 
        symbol: str, 
        dte: int,
        center_delta: float, 
        wing_width: int
    ) -> Dict[str, OptionData]:
        """
        Select strikes for a put butterfly strategy
        
        Args:
            symbol: Underlying symbol (e.g., "SPX")
            dte: DTE for all options
            center_delta: Target delta for center strike (positive value)
            wing_width: Strike width for wings in points
            
        Returns:
            Dict[str, OptionData]: Selected option data keyed by leg name
        """
        # Calculate expiry date
        expiry = self.get_expiry_date(dte)
        
        logger.info(f"Selecting strikes for put fly: {symbol} "
                   f"DTE: {dte} (expiry: {expiry}), "
                   f"Center delta: {center_delta}, "
                   f"Wing width: {wing_width}")
        
        # Get option chain
        option_chain = self.get_option_chain(symbol, expiry)
        
        if not option_chain:
            logger.error("Failed to get option chain")
            return {}
        
        # Select center strike based on delta
        center_put = self.find_strike_by_delta(option_chain, center_delta, "P")
        
        if not center_put:
            logger.error("Failed to select center leg")
            return {}
        
        # Select wing options
        lower_put = self.find_strike_by_offset(option_chain, center_put.strike, -wing_width, "P")
        upper_put = self.find_strike_by_offset(option_chain, center_put.strike, wing_width, "P")
        
        if not lower_put or not upper_put:
            logger.error("Failed to select wing legs")
            return {}
        
        # Return selected strikes
        return {
            "center_put": center_put,  # Sell 2x
            "lower_put": lower_put,    # Buy 1x
            "upper_put": upper_put     # Buy 1x
        }
    
    def select_iron_condor_strikes(self, option_chain: List[OptionData], short_delta: float, wing_width: float) -> Optional[Dict]:
        """
        Select strikes for an iron condor strategy
        
        Args:
            option_chain: Option chain data
            short_delta: Delta for short strikes (absolute value, e.g. 0.16 or 16%)
            wing_width: Wing width in points
            
        Returns:
            Optional[Dict]: Dictionary with selected option data for each leg
        """
        if not option_chain:
            self.logger.error("Empty option chain provided")
            return None
        
        # Get current price and expiration
        expiry = option_chain[0].expiry
        
        # Estimate current underlying price - find ATM options
        atm_options = [opt for opt in option_chain if abs(abs(opt.delta) - 0.5) < 0.05]
        if atm_options:
            # Find the average strike of options with delta near 0.5/-0.5
            estimated_price = sum(opt.strike for opt in atm_options) / len(atm_options)
        else:
            # Fallback - assumes strikes are centered around current price
            all_strikes = sorted(set(opt.strike for opt in option_chain))
            midpoint_index = len(all_strikes) // 2
            estimated_price = all_strikes[midpoint_index]
        
        self.logger.info(f"Selecting iron condor strikes for {expiry}")
        self.logger.info(f"Estimated underlying price: {estimated_price}")
        self.logger.info(f"Target short delta: {short_delta:.3f} (absolute), wing width: {wing_width}")
        
        # Filter by option type and separate strikes
        # Using absolute value for finding puts with specified delta
        calls = [opt for opt in option_chain if opt.option_type == "C"]
        puts = [opt for opt in option_chain if opt.option_type == "P"]
        
        # Filter for OTM options only
        otm_calls = [opt for opt in calls if opt.strike > estimated_price]
        otm_puts = [opt for opt in puts if opt.strike < estimated_price]
        
        # Sort by strike
        otm_calls = sorted(otm_calls, key=lambda x: x.strike)
        otm_puts = sorted(otm_puts, key=lambda x: x.strike, reverse=True)
        
        if not otm_calls or not otm_puts:
            self.logger.error("Insufficient OTM options in chain")
            return None
        
        # Log available delta ranges
        call_deltas = [round(opt.delta, 3) for opt in otm_calls[:10]]
        put_deltas = [round(abs(opt.delta), 3) for opt in otm_puts[:10]]
        
        self.logger.info(f"Available OTM call deltas: {call_deltas}")
        self.logger.info(f"Available OTM put deltas: {put_deltas}")
        
        # Find short strikes - using absolute value to compare put deltas
        self.logger.info(f"Finding short call with delta close to {short_delta:.3f}")
        short_call = min(otm_calls, key=lambda x: abs(x.delta - short_delta))
        
        self.logger.info(f"Finding short put with delta close to {short_delta:.3f}")
        short_put = min(otm_puts, key=lambda x: abs(abs(x.delta) - short_delta))
        
        if not short_call or not short_put:
            self.logger.error("Could not find suitable short strikes")
            return None
        
        # Log the selected short strikes
        self.logger.info(f"Selected short call: strike {short_call.strike}, delta {short_call.delta:.3f}")
        self.logger.info(f"Selected short put: strike {short_put.strike}, delta {short_put.delta:.3f} (abs: {abs(short_put.delta):.3f})")
        
        # Find long strikes by absolute offset (wing width)
        # For iron condor: long call > short call, long put < short put
        long_call_target = short_call.strike + wing_width
        long_put_target = short_put.strike - wing_width
        
        # Find closest available strikes
        long_call = min(calls, key=lambda x: abs(x.strike - long_call_target))
        long_put = min(puts, key=lambda x: abs(x.strike - long_put_target))
        
        if not long_call or not long_put:
            self.logger.error("Could not find suitable long strikes")
            return None
        
        # Log the full iron condor setup
        self.logger.info(f"Iron condor strikes for {expiry}:")
        self.logger.info(f"Long put:   {long_put.strike} (delta: {long_put.delta:.3f})")
        self.logger.info(f"Short put:  {short_put.strike} (delta: {short_put.delta:.3f})")
        self.logger.info(f"Short call: {short_call.strike} (delta: {short_call.delta:.3f})")
        self.logger.info(f"Long call:  {long_call.strike} (delta: {long_call.delta:.3f})")
        
        # Return the selected strikes
        return {
            "short_put": short_put,
            "long_put": long_put,
            "short_call": short_call,
            "long_call": long_call
        }
    
    def select_put_butterfly_strikes(self, option_chain: List[OptionData], short_delta: float, wing_width: float) -> Optional[Dict]:
        """
        Select strikes for a put butterfly strategy
        
        Args:
            option_chain: Option chain data
            short_delta: Delta for short strikes (absolute value)
            wing_width: Wing width in points
            
        Returns:
            Optional[Dict]: Dictionary with selected option data for each leg
        """
        self.logger.info(f"Selecting put butterfly strikes with short delta {short_delta} and wing width {wing_width}")
        
        # Filter puts
        puts = [option for option in option_chain if option.option_type == "P"]
        
        if not puts:
            self.logger.error("No puts found in option chain")
            return None
        
        # Sort by delta
        puts = sorted(puts, key=lambda x: abs(x.delta))
        
        # Find middle strike by delta
        middle_put = self.find_option_by_delta(puts, short_delta)
        
        if not middle_put:
            self.logger.error(f"Could not find middle strike with delta {short_delta}")
            return None
        
        # Find wing strikes by offset
        lower_put = self.find_strike_by_offset(option_chain, middle_put.strike, -wing_width, "P")
        upper_put = self.find_strike_by_offset(option_chain, middle_put.strike, wing_width, "P")
        
        if not lower_put or not upper_put:
            self.logger.error(f"Could not find wing strikes with offset {wing_width}")
            return None
        
        # Log the selected strikes
        self.logger.info(f"Selected put butterfly strikes:")
        self.logger.info(f"Lower wing: {lower_put.strike} (delta: {lower_put.delta:.3f})")
        self.logger.info(f"Middle: {middle_put.strike} (delta: {middle_put.delta:.3f})")
        self.logger.info(f"Upper wing: {upper_put.strike} (delta: {upper_put.delta:.3f})")
        
        # Return the selected strikes
        return {
            "lower_put": lower_put,
            "middle_put": middle_put,
            "upper_put": upper_put
        }
    
    def select_double_calendar_strikes(self, front_chain: List[OptionData], back_chain: List[OptionData], short_delta: float) -> Optional[Dict]:
        """
        Select strikes for a double calendar strategy
        
        Args:
            front_chain: Front month option chain
            back_chain: Back month option chain
            short_delta: Delta for short strikes (absolute value)
            
        Returns:
            Optional[Dict]: Dictionary with selected option data for each leg
        """
        self.logger.info(f"Selecting double calendar strikes with short delta {short_delta}")
        
        # Filter options by type
        front_calls = [option for option in front_chain if option.option_type == "C"]
        front_puts = [option for option in front_chain if option.option_type == "P"]
        back_calls = [option for option in back_chain if option.option_type == "C"]
        back_puts = [option for option in back_chain if option.option_type == "P"]
        
        if not front_calls or not front_puts or not back_calls or not back_puts:
            self.logger.error("Missing options in one of the chains")
            return None
        
        # Sort by delta
        front_calls = sorted(front_calls, key=lambda x: abs(x.delta))
        front_puts = sorted(front_puts, key=lambda x: abs(x.delta))
        
        # Find short strikes by delta
        short_call = self.find_option_by_delta(front_calls, short_delta)
        short_put = self.find_option_by_delta(front_puts, short_delta)
        
        if not short_call or not short_put:
            self.logger.error(f"Could not find short strikes with delta {short_delta}")
            return None
        
        # Find back month options with the same strikes
        back_call = self.find_option_by_strike(back_calls, short_call.strike)
        back_put = self.find_option_by_strike(back_puts, short_put.strike)
        
        if not back_call or not back_put:
            self.logger.error(f"Could not find back month options with matching strikes")
            return None
        
        # Log the selected strikes
        self.logger.info(f"Selected double calendar strikes:")
        self.logger.info(f"Front month put: {short_put.strike} (delta: {short_put.delta:.3f})")
        self.logger.info(f"Back month put: {back_put.strike} (delta: {back_put.delta:.3f})")
        self.logger.info(f"Front month call: {short_call.strike} (delta: {short_call.delta:.3f})")
        self.logger.info(f"Back month call: {back_call.strike} (delta: {back_call.delta:.3f})")
        
        # Return the selected strikes
        return {
            "front_put": short_put,
            "back_put": back_put,
            "front_call": short_call,
            "back_call": back_call
        }
    
    def find_option_by_delta(self, options: List[OptionData], target_delta: float) -> Optional[OptionData]:
        """
        Find option with delta closest to target
        
        Args:
            options: List of options
            target_delta: Target delta (absolute value)
            
        Returns:
            Optional[OptionData]: Option with closest delta
        """
        if not options:
            self.logger.warning("Empty options list provided")
            return None
        
        # Determine if we're dealing with calls or puts
        is_call = options[0].option_type == "C"
        
        # Make target_delta positive for comparison
        target_delta = abs(target_delta)
        
        # For calls: find option with delta closest to target_delta
        # For puts: find option with abs(delta) closest to target_delta
        if is_call:
            closest_option = min(options, key=lambda x: abs(x.delta - target_delta))
            self.logger.info(f"Looking for call with delta ~{target_delta:.3f}, found: {closest_option.delta:.3f}")
        else:
            closest_option = min(options, key=lambda x: abs(abs(x.delta) - target_delta))
            self.logger.info(f"Looking for put with delta ~-{target_delta:.3f}, found: {closest_option.delta:.3f}")
        
        if closest_option:
            # Log some nearby options to help with debugging
            sorted_options = sorted(options, key=lambda x: abs(abs(x.delta) - target_delta))
            self.logger.info(f"Options near target delta {target_delta:.3f}:")
            for i in range(min(5, len(sorted_options))):
                opt = sorted_options[i]
                self.logger.info(f"  Strike {opt.strike}: delta {opt.delta:.3f}{' ← selected' if i == 0 else ''}")
        
        return closest_option
    
    def find_option_by_strike(self, options: List[OptionData], target_strike: float) -> Optional[OptionData]:
        """
        Find option with the specified strike
        
        Args:
            options: List of options
            target_strike: Target strike price
            
        Returns:
            Optional[OptionData]: Option with the specified strike
        """
        if not options:
            self.logger.warning("Empty options list provided")
            return None
            
        # Find option with the exact strike, or closest if not found
        matching_options = [option for option in options if abs(option.strike - target_strike) < 0.01]
        
        if matching_options:
            # If exact matches found, return the first one
            option = matching_options[0]
            self.logger.info(f"Found exact strike match: {option.strike}")
            return option
        else:
            # Otherwise find closest strike
            closest_option = min(options, key=lambda x: abs(x.strike - target_strike))
            self.logger.info(f"Found closest strike {closest_option.strike} to target {target_strike}")
            return closest_option
