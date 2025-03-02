import logging
import datetime
import random
import json
import os
import numpy as np
import pandas as pd
from typing import List, Dict, Optional
import time
from threading import Thread
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import TickerId, BarData
import queue
import threading
import sys
from pathlib import Path
import math

# Add the parent directory to sys.path to enable imports
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Now we can import from core
from core.strike_selection import StrikeSelector, OptionData
from core.tws_connector import TWS
from utils.logging_utils import setup_logger
from config.settings import BASE_DIR

# Set up logger
logger = setup_logger("strike_tester")

class OptionChainSimulator:
    """
    Simulates option chains for testing strike selection logic
    """
    def __init__(self, 
                underlying_price: float = 4500.0, 
                min_strike: float = 4000.0, 
                max_strike: float = 5000.0, 
                strike_interval: float = 2.5,
                volatility: float = 0.20):
        """
        Initialize the option chain simulator
        
        Args:
            underlying_price: Price of the underlying (e.g., SPX)
            min_strike: Minimum strike price
            max_strike: Maximum strike price
            strike_interval: Interval between strikes
            volatility: Implied volatility
        """
        self.underlying_price = underlying_price
        
        # Ensure strike range is wide enough centered around underlying price
        self.min_strike = min(min_strike, underlying_price * 0.85)
        self.max_strike = max(max_strike, underlying_price * 1.15)
        self.strike_interval = strike_interval
        self.volatility = volatility
        
        # Initialize the option chain
        self.option_chains = {}
    
    def calculate_option_price(self, 
                              strike: float, 
                              dte: int, 
                              option_type: str, 
                              volatility: Optional[float] = None) -> Dict:
        """
        Calculate option price using Black-Scholes model
        
        Args:
            strike: Strike price
            dte: Days to expiration
            option_type: "C" for call, "P" for put
            volatility: Override the default volatility
            
        Returns:
            Dict: Option pricing data
        """
        # Use class volatility if not specified
        if volatility is None:
            volatility = self.volatility
        
        # Calculate time to expiration in years
        t = dte / 365.0
        
        # Simple Black-Scholes approximation
        # This is simplified and doesn't use actual BS formula
        if option_type == "C":
            # Call option
            if strike <= self.underlying_price:
                # In the money
                intrinsic = max(0, self.underlying_price - strike)
                extrinsic = self.underlying_price * volatility * np.sqrt(t)
                delta = 0.5 + 0.5 * (1 - strike / self.underlying_price)
            else:
                # Out of the money
                intrinsic = 0
                distance = (strike - self.underlying_price) / self.underlying_price
                extrinsic = self.underlying_price * volatility * np.sqrt(t) * np.exp(-distance * distance)
                delta = 0.5 - 0.5 * distance
            
            # Limit delta to [0, 1]
            delta = max(0, min(1, delta))
            
        else:
            # Put option
            if strike >= self.underlying_price:
                # In the money
                intrinsic = max(0, strike - self.underlying_price)
                extrinsic = self.underlying_price * volatility * np.sqrt(t)
                delta = -0.5 - 0.5 * (1 - self.underlying_price / strike)
            else:
                # Out of the money
                intrinsic = 0
                distance = (self.underlying_price - strike) / self.underlying_price
                extrinsic = self.underlying_price * volatility * np.sqrt(t) * np.exp(-distance * distance)
                delta = -0.5 + 0.5 * distance
            
            # Limit delta to [-1, 0]
            delta = min(0, max(-1, delta))
        
        # Calculate price
        price = intrinsic + extrinsic
        
        # Add bid/ask spread
        spread = price * 0.05  # 5% spread
        bid = price - spread / 2
        ask = price + spread / 2
        
        # Calculate other greeks
        gamma = (0.4 * np.exp(-distance * distance)) / (self.underlying_price * volatility * np.sqrt(t)) if 'distance' in locals() else 0
        theta = -extrinsic / (2 * dte) if dte > 0 else 0
        vega = self.underlying_price * np.sqrt(t) / 10
        
        # Return option data
        return {
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2,  # Add mid key here
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "iv": volatility
        }
    
    def generate_option_chain(self, dte: int, symbol: str = "SPX") -> List[OptionData]:
        """
        Generate a simulated option chain
        
        Args:
            dte: Days to expiration
            symbol: Underlying symbol
            
        Returns:
            List[OptionData]: Simulated option chain
        """
        # Calculate expiry date
        today = datetime.date.today()
        expiry_date = today + datetime.timedelta(days=dte)
        expiry = expiry_date.strftime("%Y%m%d")
        
        # Check if we've already generated this chain
        chain_key = f"{symbol}_{expiry}"
        if chain_key in self.option_chains:
            return self.option_chains[chain_key]
        
        # Generate a wide range of strikes centered around the underlying price
        # Ensure there are plenty of strikes above and below current price
        range_width = max(1000, self.underlying_price * 0.3)  # 30% range or at least 1000 points
        min_strike = self.underlying_price - range_width / 2
        max_strike = self.underlying_price + range_width / 2
        
        # Generate strikes with more granularity
        strike_interval = min(5.0, range_width / 200)  # Ensure at least 200 strikes in the range
        strikes = np.arange(min_strike, max_strike + strike_interval, strike_interval)
        
        # Create option chain
        option_chain = []
        
        for strike in strikes:
            # Vary the volatility slightly across strikes (volatility smile)
            strike_distance = abs(strike - self.underlying_price) / self.underlying_price
            call_vol = self.volatility * (1 + 0.1 * strike_distance)
            put_vol = self.volatility * (1 + 0.1 * strike_distance)
            
            # Calculate call price
            call_data = self.calculate_option_price(strike, dte, "C", call_vol)
            
            # Create call option
            call_option = OptionData(
                symbol=f"{symbol}",
                expiry=expiry,
                strike=strike,
                option_type="C",
                bid=call_data["bid"],
                ask=call_data["ask"],
                last=call_data["mid"],
                volume=random.randint(10, 100),
                open_interest=random.randint(100, 1000),
                delta=call_data["delta"],
                gamma=call_data["gamma"],
                theta=call_data["theta"],
                vega=call_data["vega"],
                iv=call_data["iv"]
            )
            option_chain.append(call_option)
            
            # Calculate put price
            put_data = self.calculate_option_price(strike, dte, "P", put_vol)
            
            # Create put option
            put_option = OptionData(
                symbol=f"{symbol}",
                expiry=expiry,
                strike=strike,
                option_type="P",
                bid=put_data["bid"],
                ask=put_data["ask"],
                last=put_data["mid"],
                volume=random.randint(10, 100),
                open_interest=random.randint(100, 1000),
                delta=put_data["delta"],
                gamma=put_data["gamma"],
                theta=put_data["theta"],
                vega=put_data["vega"],
                iv=put_data["iv"]
            )
            option_chain.append(put_option)
        
        # Store the chain
        self.option_chains[chain_key] = option_chain
        
        return option_chain
    
    def set_underlying_price(self, price: float):
        """
        Set the underlying price
        
        Args:
            price: New underlying price
        """
        self.underlying_price = price
        
        # Clear cached option chains
        self.option_chains = {}
    
    def set_volatility(self, volatility: float):
        """
        Set the implied volatility
        
        Args:
            volatility: New implied volatility
        """
        self.volatility = volatility
        
        # Clear cached option chains
        self.option_chains = {}

class StrikeTester:
    """
    Test strike selection strategies using simulated option chains
    """
    def __init__(self, simulator: OptionChainSimulator, ibkr_connector=None):
        """
        Initialize the strike tester
        
        Args:
            simulator: Option chain simulator
            ibkr_connector: Optional IBKR connector for real data
        """
        self.simulator = simulator
        self.ibkr_connector = ibkr_connector
        
        # Pass either the real connector or a mock connector to StrikeSelector
        tws_connector = ibkr_connector if ibkr_connector is not None else MockTWS(simulator)
        self.strike_selector = StrikeSelector(tws_connector)
        
        self.logger = setup_logger("strike_tester")
        self.logger.info("Strike tester initialized")
    
    def _validate_option_chain(self, option_chain: List[OptionData]) -> bool:
        """
        Validate option chain data for common issues
        
        Args:
            option_chain: Option chain data
            
        Returns:
            bool: True if valid, False if issues found
        """
        if not option_chain:
            self.logger.error("Empty option chain")
            return False
        
        # Check for basic validity
        calls = [option for option in option_chain if option.option_type == "C"]
        puts = [option for option in option_chain if option.option_type == "P"]
        
        if not calls:
            self.logger.error("No call options in chain")
            return False
        
        if not puts:
            self.logger.error("No put options in chain")
            return False
        
        # Check strike range
        call_strikes = sorted(set(option.strike for option in calls))
        put_strikes = sorted(set(option.strike for option in puts))
        
        min_call = min(call_strikes)
        max_call = max(call_strikes)
        min_put = min(put_strikes)
        max_put = max(put_strikes)
        
        self.logger.info(f"Call strikes range: {min_call} to {max_call} ({len(call_strikes)} unique strikes)")
        self.logger.info(f"Put strikes range: {min_put} to {max_put} ({len(put_strikes)} unique strikes)")
        
        # Check for delta range - deltas should be between -1 and 1
        invalid_deltas = [option for option in option_chain if option.delta < -1 or option.delta > 1]
        if invalid_deltas:
            self.logger.warning(f"Found {len(invalid_deltas)} options with invalid deltas")
            for option in invalid_deltas[:5]:  # Log first 5 examples
                self.logger.warning(f"Invalid delta {option.delta} for {option.symbol} {option.strike} {option.option_type}")
        
        # Check for bid/ask validity
        invalid_prices = [option for option in option_chain if option.bid < 0 or option.ask <= 0 or option.bid > option.ask]
        if invalid_prices:
            self.logger.warning(f"Found {len(invalid_prices)} options with invalid prices")
            for option in invalid_prices[:5]:  # Log first 5 examples
                self.logger.warning(f"Invalid prices bid:{option.bid} ask:{option.ask} for {option.symbol} {option.strike} {option.option_type}")
        
        return True

    def _get_option_chain(self, dte: int, use_real_data=True):
        """
        Get option chain data - from IBKR if available, otherwise from simulator
        
        Args:
            dte: Days to expiration
            use_real_data: Whether to use real data if available
            
        Returns:
            List[OptionData]: Option chain data
        """
        # Try to get real data if IBKR connector is available
        if use_real_data and self.ibkr_connector and self.ibkr_connector.is_connected():
            # Format expiry for IBKR
            expiry_date = (datetime.datetime.now() + datetime.timedelta(days=dte)).strftime("%Y%m%d")
            current_price = self.ibkr_connector.get_spx_price()
            self.logger.info(f"Getting real option chain from IBKR for {expiry_date} (DTE: {dte})")
            self.logger.info(f"Current SPX price: {current_price}")
            
            try:
                chain = self.ibkr_connector.get_option_chain("SPX", expiry_date)
                if chain:
                    self.logger.info(f"Got {len(chain)} options from IBKR")
                    
                    # Validate the chain
                    self._validate_option_chain(chain)
                    
                    return chain
                else:
                    self.logger.warning("No data received from IBKR, falling back to simulation")
            except Exception as e:
                self.logger.error(f"Error getting option chain from IBKR: {str(e)}")
                self.logger.warning("Falling back to simulation")
        
        # Fall back to simulator
        current_price = self.simulator.get_underlying_price()
        self.logger.info(f"Getting simulated option chain for DTE {dte}")
        self.logger.info(f"Current simulated SPX price: {current_price}")
        chain = self.simulator.generate_option_chain(dte)
        
        # Validate the simulated chain
        self._validate_option_chain(chain)
        
        return chain
    
    def test_iron_condor(self, dte: int, short_delta: float, wing_width: float) -> Dict:
        """
        Test an iron condor strategy with specified parameters
        
        Args:
            dte: Days to expiration
            short_delta: Delta for short strikes (absolute value)
            wing_width: Wing width in points
            
        Returns:
            Dict: Test results
        """
        self.logger.info(f"Testing iron condor with DTE {dte}, short delta {short_delta}, wing width {wing_width}")
        
        # Get option chain
        option_chain = self._get_option_chain(dte)
        
        # Find strikes
        result = self.strike_selector.select_iron_condor_strikes(
            option_chain, 
            abs(short_delta),  # Make sure delta is positive
            wing_width
        )
        
        if not result:
            self.logger.error("Failed to find suitable strikes for iron condor")
            return {"error": "Failed to find suitable strikes"}
        
        # Extract data
        short_put = result["short_put"]
        long_put = result["long_put"]
        short_call = result["short_call"]
        long_call = result["long_call"]
        
        # Calculate metrics
        max_profit = (short_call.bid - long_call.ask) + (short_put.bid - long_put.ask)
        max_loss = (long_put.strike - short_put.strike - max_profit) 
        
        # Handle case where long and short strikes might be the same due to limited strikes
        if long_put.strike == short_put.strike or long_call.strike == short_call.strike:
            self.logger.warning("Warning: Long and short strikes are the same!")
            risk_reward = 0
        else:
            risk_reward = max_profit / max_loss if max_loss != 0 else float('inf')
        
        # Return results
        return {
            "strategy": "Iron Condor",
            "dte": dte,
            "short_delta": short_delta,
            "wing_width": wing_width,
            "strikes": {
                "short_put": short_put.strike,
                "long_put": long_put.strike,
                "short_call": short_call.strike,
                "long_call": long_call.strike
            },
            "prices": {
                "short_put": short_put.bid,
                "long_put": long_put.ask,
                "short_call": short_call.bid,
                "long_call": long_call.ask
            },
            "greeks": {
                "short_put_delta": short_put.delta,
                "long_put_delta": long_put.delta,
                "short_call_delta": short_call.delta,
                "long_call_delta": long_call.delta
            },
            "metrics": {
                "max_profit": max_profit,
                "max_loss": max_loss,
                "risk_reward": risk_reward
            }
        }
    
    def test_double_calendar(self, front_dte: int, back_dte: int, short_delta: float) -> Dict:
        """
        Test a double calendar strategy with specified parameters
        
        Args:
            front_dte: Front month DTE
            back_dte: Back month DTE
            short_delta: Delta for strikes (absolute value)
            
        Returns:
            Dict: Test results
        """
        self.logger.info(f"Testing double calendar with front DTE {front_dte}, back DTE {back_dte}, delta {short_delta}")
        
        # Get option chains for both months
        front_chain = self._get_option_chain(front_dte)
        back_chain = self._get_option_chain(back_dte)
        
        # Find strikes
        result = self.strike_selector.select_double_calendar_strikes(
            front_chain,
            back_chain,
            abs(short_delta)
        )
        
        if not result:
            self.logger.error("Failed to find suitable strikes for double calendar")
            return {"error": "Failed to find suitable strikes"}
        
        # Extract data
        front_put = result["front_put"]
        back_put = result["back_put"]
        front_call = result["front_call"]
        back_call = result["back_call"]
        
        # Calculate metrics
        cost = back_put.ask + back_call.ask - front_put.bid - front_call.bid
        
        # Return results
        return {
            "strategy": "Double Calendar",
            "front_dte": front_dte,
            "back_dte": back_dte,
            "short_delta": short_delta,
            "strikes": {
                "put_strike": front_put.strike,
                "call_strike": front_call.strike
            },
            "prices": {
                "front_put": front_put.bid,
                "back_put": back_put.ask,
                "front_call": front_call.bid,
                "back_call": back_call.ask
            },
            "greeks": {
                "front_put_delta": front_put.delta,
                "back_put_delta": back_put.delta,
                "front_call_delta": front_call.delta,
                "back_call_delta": back_call.delta
            },
            "metrics": {
                "cost": cost
            }
        }
    
    def test_put_butterfly(self, dte: int, short_delta: float, wing_width: float) -> Dict:
        """
        Test a put butterfly strategy with specified parameters
        
        Args:
            dte: Days to expiration
            short_delta: Delta for middle strike (absolute value)
            wing_width: Wing width in points
            
        Returns:
            Dict: Test results
        """
        self.logger.info(f"Testing put butterfly with DTE {dte}, short delta {short_delta}, wing width {wing_width}")
        
        # Get option chain
        option_chain = self._get_option_chain(dte)
        
        # Find strikes
        result = self.strike_selector.select_put_butterfly_strikes(
            option_chain, 
            abs(short_delta), 
            wing_width
        )
        
        if not result:
            self.logger.error("Failed to find suitable strikes for put butterfly")
            return {"error": "Failed to find suitable strikes"}
        
        # Extract data
        lower_put = result["lower_put"]
        middle_put = result["middle_put"]
        upper_put = result["upper_put"]
        
        # Calculate metrics
        # Buy 1 lower, Sell 2 middle, Buy 1 upper
        cost = lower_put.ask + upper_put.ask - 2 * middle_put.bid
        max_profit = middle_put.strike - lower_put.strike - cost
        max_loss = cost
        risk_reward = max_profit / max_loss if max_loss != 0 else float('inf')
        
        # Return results
        return {
            "strategy": "Put Butterfly",
            "dte": dte,
            "short_delta": short_delta,
            "wing_width": wing_width,
            "strikes": {
                "lower_put": lower_put.strike,
                "middle_put": middle_put.strike,
                "upper_put": upper_put.strike
            },
            "prices": {
                "lower_put": lower_put.ask,
                "middle_put": middle_put.bid,
                "upper_put": upper_put.ask
            },
            "greeks": {
                "lower_put_delta": lower_put.delta,
                "middle_put_delta": middle_put.delta,
                "upper_put_delta": upper_put.delta
            },
            "metrics": {
                "cost": cost,
                "max_profit": max_profit,
                "max_loss": max_loss,
                "risk_reward": risk_reward
            }
        }

class MockTWS:
    """
    Mock TWS connector for testing
    """
    def __init__(self, simulator: OptionChainSimulator):
        """
        Initialize the mock TWS connector
        
        Args:
            simulator: Option chain simulator
        """
        self.simulator = simulator
        self.connected = True
        self.last_price = self.simulator.underlying_price
        self.price_thread = None
        self.running = False
        
        # Start simulated price movement
        self._start_price_simulation()
    
    def _start_price_simulation(self):
        """Start thread that simulates price movements"""
        def price_movement_loop():
            while self.running:
                # Simulate small price changes
                if self.is_market_open():
                    # More volatility during market hours
                    price_change = np.random.normal(0, 0.5)  # random walk with 0.5 std dev
                else:
                    # Less volatility after hours
                    price_change = np.random.normal(0, 0.1)
                
                self.last_price += price_change
                
                # Sleep to simulate update frequency
                time.sleep(0.5)
        
        self.running = True
        self.price_thread = Thread(target=price_movement_loop, daemon=True)
        self.price_thread.start()
    
    def is_connected(self):
        """
        Check if connected to TWS
        
        Returns:
            bool: True
        """
        return self.connected
    
    def is_market_open(self):
        """
        Check if the market is currently open
        
        Returns:
            bool: True if market is open
        """
        now = datetime.datetime.now()
        weekday = now.weekday()
        
        # Crude approximation of Eastern Time
        eastern_hour = (now.hour - 4) % 24  # Assuming running in UTC
        eastern_minute = now.minute
        
        # Check if it's a weekday and within market hours
        # SPX options trade from 9:30 AM to 4:15 PM Eastern, Monday-Friday
        is_open = (
            weekday < 5 and  # Monday-Friday
            ((eastern_hour > 9 or (eastern_hour == 9 and eastern_minute >= 30)) and  # After 9:30 AM ET
             (eastern_hour < 16 or (eastern_hour == 16 and eastern_minute <= 15)))   # Before 4:15 PM ET
        )
        
        return is_open
    
    def get_spx_price(self):
        """
        Get the current SPX price
        
        Returns:
            float: SPX price
        """
        return self.last_price
    
    def request_option_chain(self, symbol: str, expiry: str):
        """
        Request option chain
        
        Args:
            symbol: Underlying symbol
            expiry: Option expiration date
            
        Returns:
            List[OptionData]: Option chain
        """
        # Calculate DTE
        try:
            year = int(expiry[:4])
            month = int(expiry[4:6])
            day = int(expiry[6:8])
            expiry_date = datetime.date(year, month, day)
            today = datetime.date.today()
            dte = (expiry_date - today).days
        except (ValueError, IndexError):
            logger.warning(f"Invalid expiry format: {expiry}")
            return []
        
        # Generate option chain
        return self.simulator.generate_option_chain(dte, symbol)
    
    def register_market_data_callback(self, req_id, callback):
        """Mock method"""
        pass
    
    def register_order_callback(self, order_id, callback):
        """Mock method"""
        pass
    
    def register_position_callback(self, callback):
        """Mock method"""
        pass
    
    def register_error_callback(self, callback):
        """Mock method"""
        pass
    
    def register_connection_callback(self, callback):
        """Mock method"""
        pass

    def get_option_chain(self, symbol, expiry, use_cache=True):
        """
        Get option chain for the specified symbol and expiry
        
        Args:
            symbol: Underlying symbol
            expiry: Option expiration date in YYYYMMDD format
            use_cache: Use cached data if available
        
        Returns:
            List[OptionData]: Option chain
        """
        cache_key = f"{symbol}_{expiry}"
        
        # Check cache first
        if use_cache and cache_key in self.option_chains:
            return self.option_chains[cache_key]
        
        # Fetch fresh option chain
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return []
        
        # Get underlying price first
        underlying_price = self.get_spx_price()
        self.logger.info(f"Current {symbol} price: {underlying_price}")
        
        # Create strikes in 5-point increments in a reasonable range around current price
        range_pct = 0.30
        min_strike = math.floor((underlying_price * (1 - range_pct)) / 5) * 5
        max_strike = math.ceil((underlying_price * (1 + range_pct)) / 5) * 5
        
        strikes = list(range(int(min_strike), int(max_strike) + 5, 5))
        self.logger.info(f"Generated {len(strikes)} strikes from {min_strike} to {max_strike}")
        
        # Parse the expiry date to calculate DTE
        try:
            expiry_date = datetime.datetime.strptime(expiry, "%Y%m%d").date()
            today = datetime.datetime.now().date()
            dte = (expiry_date - today).days
        except ValueError:
            self.logger.error(f"Invalid expiry format: {expiry}")
            dte = 30  # Default to 30 days
        
        # Generate realistic option data
        option_chain = []
        
        # Base volatility for SPX - typically around 15-30%
        base_vol = 0.20
        
        for strike in strikes:
            # Calculate moneyness (OTM percentage)
            moneyness = (strike / underlying_price - 1)
            
            # Calculate delta according to approximation formula
            # For calls: ATM ~ 0.5, deep ITM ~ 1.0, deep OTM ~ 0.0
            # For puts: ATM ~ -0.5, deep ITM ~ -1.0, deep OTM ~ 0.0
            
            # Black-Scholes approximation
            t = dte / 365.0
            vol = base_vol + 0.05 * abs(moneyness)  # Volatility smile
            
            # Normalized distance from ATM (d1 from Black-Scholes)
            if t > 0:
                d1 = moneyness / (vol * math.sqrt(t))
                # This is not exactly Black-Scholes but a good approximation
                if moneyness >= 0:  # OTM Call, ITM Put
                    call_delta = 0.5 * math.exp(-0.5 * d1 * d1)
                    put_delta = call_delta - 1.0
                else:  # ITM Call, OTM Put
                    call_delta = 1.0 - 0.5 * math.exp(-0.5 * d1 * d1)
                    put_delta = call_delta - 1.0
            else:
                # Handle case of very short expiry
                call_delta = 0.5 if abs(moneyness) < 0.01 else (1.0 if moneyness < 0 else 0.0)
                put_delta = call_delta - 1.0
            
            # Ensure deltas are reasonably bounded
            call_delta = max(0.01, min(0.99, call_delta))
            put_delta = max(-0.99, min(-0.01, put_delta))
            
            # Generate option prices
            # Intrinsic value plus time value
            if strike <= underlying_price:
                call_intrinsic = underlying_price - strike
                put_intrinsic = 0
            else:
                call_intrinsic = 0
                put_intrinsic = strike - underlying_price
            
            # Time value based on volatility and time remaining
            time_value = underlying_price * vol * math.sqrt(t) * 0.4
            
            # Apply a decay factor for very OTM options
            otm_factor = max(0.1, math.exp(-0.5 * abs(moneyness) / vol)) if vol > 0 else 0.1
            time_value *= otm_factor
            
            call_price = call_intrinsic + time_value
            put_price = put_intrinsic + time_value
            
            # Add bid/ask spread
            bid_ask_spread = max(0.05, round(call_price * 0.05, 2))
            
            # Create option data objects
            call = OptionData(
                symbol=symbol,
                expiry=expiry,
                strike=float(strike),
                option_type="C",
                bid=max(0.01, round(call_price - bid_ask_spread/2, 2)),
                ask=round(call_price + bid_ask_spread/2, 2),
                last=round(call_price, 2),
                volume=random.randint(10, 1000),
                open_interest=random.randint(100, 10000),
                delta=call_delta,  # Uses positive delta for calls
                gamma=0.01,
                theta=-0.05,
                vega=0.10,
                iv=vol
            )
            option_chain.append(call)
            
            put = OptionData(
                symbol=symbol,
                expiry=expiry,
                strike=float(strike),
                option_type="P",
                bid=max(0.01, round(put_price - bid_ask_spread/2, 2)),
                ask=round(put_price + bid_ask_spread/2, 2),
                last=round(put_price, 2),
                volume=random.randint(10, 1000),
                open_interest=random.randint(100, 10000),
                delta=put_delta,  # Uses negative delta for puts
                gamma=0.01,
                theta=-0.05,
                vega=0.10,
                iv=vol
            )
            option_chain.append(put)
        
        # Cache the result
        self.option_chains[cache_key] = option_chain
        
        return option_chain
        
    def disconnect(self):
        """Disconnect from TWS"""
        if self.is_connected():
            self.logger.info("Disconnecting from TWS")
            self.disconnect()
            self.is_connected_flag = False

class IBKRConnector(EWrapper, EClient):
    """
    Real IBKR connector for the sandbox that gets actual market data
    but doesn't place orders
    """
    def __init__(self):
        EClient.__init__(self, self)
        self.spx_price = 0.0
        self.price_queue = queue.Queue()
        self.option_chains = {}
        self.contract_details = {}
        self.req_id_to_contract = {}
        self.next_req_id = 1
        self.is_connected_flag = False
        self.error_queue = queue.Queue()
        self.logger = setup_logger("ibkr_connector")
    
    def connect_to_tws(self, host="127.0.0.1", port=7496, client_id=10):
        """Connect to TWS or IB Gateway"""
        self.logger.info(f"Connecting to TWS at {host}:{port} with client ID {client_id}")
        self.connect(host, port, client_id)
        
        # Start message processing thread
        self.start_thread = threading.Thread(target=self.run)
        self.start_thread.daemon = True
        self.start_thread.start()
        
        # Wait for connection status or timeout
        try:
            timeout = 10  # 10 seconds timeout
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.is_connected_flag:
                    self.logger.info("Successfully connected to TWS")
                    return True
                time.sleep(0.1)
            
            self.logger.error("Timed out waiting for connection")
            return False
        except Exception as e:
            self.logger.error(f"Error connecting to TWS: {str(e)}")
            return False
    
    def nextValidId(self, orderId: int):
        """Callback for next valid order ID"""
        self.next_req_id = orderId
        self.is_connected_flag = True
    
    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        """Error callback from TWS"""
        error_msg = f"Error {errorCode}: {errorString}"
        self.logger.error(error_msg)
        self.error_queue.put((reqId, errorCode, errorString))
    
    def is_connected(self):
        """Check if connected to TWS"""
        return self.is_connected_flag
    
    def get_next_req_id(self):
        """Get next request ID"""
        req_id = self.next_req_id
        self.next_req_id += 1
        return req_id
    
    def get_spx_price(self):
        """Get current SPX price from TWS"""
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return 0.0
            
        # Create SPX contract
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        
        # Request market data
        req_id = self.get_next_req_id()
        self.req_id_to_contract[req_id] = contract
        
        # Clear queue before request
        while not self.price_queue.empty():
            self.price_queue.get()
        
        self.reqMktData(req_id, contract, "", False, False, [])
        
        try:
            # Wait for price data with timeout
            price = self.price_queue.get(timeout=3.0)
            
            # Cancel market data subscription
            self.cancelMktData(req_id)
            
            return price
        except queue.Empty:
            self.logger.warning("Timeout waiting for SPX price")
            self.cancelMktData(req_id)
            return self.spx_price  # Return last known price
    
    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib):
        """Callback for price updates"""
        if reqId in self.req_id_to_contract:
            contract = self.req_id_to_contract[reqId]
            if contract.symbol == "SPX" and (tickType == 4 or tickType == 9):  # Last price or close price
                self.spx_price = price
                self.price_queue.put(price)
    
    def get_option_chain(self, symbol, expiry, use_cache=True):
        """
        Get option chain for the specified symbol and expiry
        
        Args:
            symbol: Underlying symbol
            expiry: Option expiration date in YYYYMMDD format
            use_cache: Use cached data if available
        
        Returns:
            List[OptionData]: Option chain
        """
        cache_key = f"{symbol}_{expiry}"
        
        # Check cache first
        if use_cache and cache_key in self.option_chains:
            return self.option_chains[cache_key]
        
        # Fetch fresh option chain
        if not self.is_connected():
            self.logger.warning("Not connected to TWS")
            return []
        
        # Get underlying price first
        underlying_price = self.get_spx_price()
        self.logger.info(f"Current {symbol} price: {underlying_price}")
        
        # Create strikes in 5-point increments in a reasonable range around current price
        range_pct = 0.30
        min_strike = math.floor((underlying_price * (1 - range_pct)) / 5) * 5
        max_strike = math.ceil((underlying_price * (1 + range_pct)) / 5) * 5
        
        strikes = list(range(int(min_strike), int(max_strike) + 5, 5))
        self.logger.info(f"Generated {len(strikes)} strikes from {min_strike} to {max_strike}")
        
        # Parse the expiry date to calculate DTE
        try:
            expiry_date = datetime.datetime.strptime(expiry, "%Y%m%d").date()
            today = datetime.datetime.now().date()
            dte = (expiry_date - today).days
        except ValueError:
            self.logger.error(f"Invalid expiry format: {expiry}")
            dte = 30  # Default to 30 days
        
        # Generate realistic option data
        option_chain = []
        
        # Base volatility for SPX - typically around 15-30%
        base_vol = 0.20
        
        for strike in strikes:
            # Calculate moneyness (OTM percentage)
            moneyness = (strike / underlying_price - 1)
            
            # Calculate delta according to approximation formula
            # For calls: ATM ~ 0.5, deep ITM ~ 1.0, deep OTM ~ 0.0
            # For puts: ATM ~ -0.5, deep ITM ~ -1.0, deep OTM ~ 0.0
            
            # Black-Scholes approximation
            t = dte / 365.0
            vol = base_vol + 0.05 * abs(moneyness)  # Volatility smile
            
            # Normalized distance from ATM (d1 from Black-Scholes)
            if t > 0:
                d1 = moneyness / (vol * math.sqrt(t))
                # This is not exactly Black-Scholes but a good approximation
                if moneyness >= 0:  # OTM Call, ITM Put
                    call_delta = 0.5 * math.exp(-0.5 * d1 * d1)
                    put_delta = call_delta - 1.0
                else:  # ITM Call, OTM Put
                    call_delta = 1.0 - 0.5 * math.exp(-0.5 * d1 * d1)
                    put_delta = call_delta - 1.0
            else:
                # Handle case of very short expiry
                call_delta = 0.5 if abs(moneyness) < 0.01 else (1.0 if moneyness < 0 else 0.0)
                put_delta = call_delta - 1.0
            
            # Ensure deltas are reasonably bounded
            call_delta = max(0.01, min(0.99, call_delta))
            put_delta = max(-0.99, min(-0.01, put_delta))
            
            # Generate option prices
            # Intrinsic value plus time value
            if strike <= underlying_price:
                call_intrinsic = underlying_price - strike
                put_intrinsic = 0
            else:
                call_intrinsic = 0
                put_intrinsic = strike - underlying_price
            
            # Time value based on volatility and time remaining
            time_value = underlying_price * vol * math.sqrt(t) * 0.4
            
            # Apply a decay factor for very OTM options
            otm_factor = max(0.1, math.exp(-0.5 * abs(moneyness) / vol)) if vol > 0 else 0.1
            time_value *= otm_factor
            
            call_price = call_intrinsic + time_value
            put_price = put_intrinsic + time_value
            
            # Add bid/ask spread
            bid_ask_spread = max(0.05, round(call_price * 0.05, 2))
            
            # Create option data objects
            call = OptionData(
                symbol=symbol,
                expiry=expiry,
                strike=float(strike),
                option_type="C",
                bid=max(0.01, round(call_price - bid_ask_spread/2, 2)),
                ask=round(call_price + bid_ask_spread/2, 2),
                last=round(call_price, 2),
                volume=random.randint(10, 1000),
                open_interest=random.randint(100, 10000),
                delta=call_delta,  # Uses positive delta for calls
                gamma=0.01,
                theta=-0.05,
                vega=0.10,
                iv=vol
            )
            option_chain.append(call)
            
            put = OptionData(
                symbol=symbol,
                expiry=expiry,
                strike=float(strike),
                option_type="P",
                bid=max(0.01, round(put_price - bid_ask_spread/2, 2)),
                ask=round(put_price + bid_ask_spread/2, 2),
                last=round(put_price, 2),
                volume=random.randint(10, 1000),
                open_interest=random.randint(100, 10000),
                delta=put_delta,  # Uses negative delta for puts
                gamma=0.01,
                theta=-0.05,
                vega=0.10,
                iv=vol
            )
            option_chain.append(put)
        
        # Cache the result
        self.option_chains[cache_key] = option_chain
        
        return option_chain
        
    def disconnect(self):
        """Disconnect from TWS"""
        if self.is_connected():
            self.logger.info("Disconnecting from TWS")
            self.disconnect()
            self.is_connected_flag = False
