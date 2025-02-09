"""Handles actual trade execution"""
from typing import Optional
from datetime import datetime
import pytz
from config.trade_config import TradeConfig, DC_CONFIG, DC_CONFIG_2, DC_CONFIG_3, DC_CONFIG_4, DC_CONFIG_5, DC_CONFIG_6
from connection.tws_manager import ConnectionManager, TWSConnector
from trading.option_finder import find_target_delta_option, get_expiry_from_dte
from trading.database import TradeDatabase
from enum import Enum

class TradeType(Enum):
    DOUBLE_CALENDAR = "DOUBLE_CALENDAR"
    IRON_CONDOR = "IRON_CONDOR"
    PUT_FLY = "PUT_FLY"
    CALL_FLY = "CALL_FLY"

class TradeExecutor:
    def __init__(self, connection_manager: ConnectionManager):
        self.connection_manager = connection_manager
    
    def execute_trade(self, config: TradeConfig) -> bool:
        """Execute a trade based on its configuration"""
        if config.trade_type == TradeType.DOUBLE_CALENDAR:
            return self.execute_double_calendar(config)
        elif config.trade_type == TradeType.IRON_CONDOR:
            return self.execute_iron_condor()
        # Add PUT_FLY and CALL_FLY here when ready
        
        return False
    
    def execute_double_calendar(self, config: TradeConfig) -> bool:
        """Execute a double calendar spread"""
        print(f"\nExecuting Double Calendar trade: {config.trade_name}")
        
        tws = self.connection_manager.get_tws()
        if not tws:
            print("No TWS connection available")
            return False
            
        # Get current market price
        spx_price = tws.spx_price
        if not spx_price:
            print("Unable to get current SPX price")
            return False
            
        print(f"Current SPX price: {spx_price}")
        
        # Calculate initial strikes based on current price
        initial_put_strike = round(spx_price / 5) * 5  # Round to nearest 5
        initial_call_strike = initial_put_strike
        
        # Get expiry dates
        near_expiry = get_expiry_from_dte(config.near_dte)
        far_expiry = get_expiry_from_dte(config.far_dte)
        
        print(f"\nLooking for options with:")
        print(f"Near-term expiry: {near_expiry} ({config.near_dte} DTE)")
        print(f"Far-term expiry: {far_expiry} ({config.far_dte} DTE)")
        
        # Find all required options
        near_put = find_target_delta_option(tws, near_expiry, "P", initial_put_strike, config.target_delta)
        if not near_put:
            print("Failed to find near-term put")
            return False
            
        far_put = find_target_delta_option(tws, far_expiry, "P", near_put.contract.strike, config.target_delta)
        if not far_put:
            print("Failed to find far-term put")
            return False
            
        near_call = find_target_delta_option(tws, near_expiry, "C", initial_call_strike, config.target_delta)
        if not near_call:
            print("Failed to find near-term call")
            return False
            
        far_call = find_target_delta_option(tws, far_expiry, "C", near_call.contract.strike, config.target_delta)
        if not far_call:
            print("Failed to find far-term call")
            return False
        
        # Submit the order
        order_id = tws.submit_double_calendar(
            short_put_contract=near_put.contract,
            long_put_contract=far_put.contract,
            short_call_contract=near_call.contract,
            long_call_contract=far_call.contract,
            quantity=config.quantity,
            total_debit=config.max_debit
        )
        
        if not order_id:
            print("Failed to submit order")
            return False
            
        # Monitor the order
        filled = tws.monitor_order(order_id, timeout_seconds=300)
        
        if filled:
            # Record the trade in database
            db = TradeDatabase()
            db.record_trade(
                trade_name=config.trade_name,
                trade_type="DOUBLE_CALENDAR",
                entry_time=datetime.now(pytz.timezone('US/Eastern')),
                near_expiry=near_expiry,
                far_expiry=far_expiry,
                put_strike=near_put.contract.strike,
                call_strike=near_call.contract.strike,
                quantity=config.quantity,
                spx_price=spx_price
            )
            return True
            
        return False
    
    def execute_iron_condor(self) -> bool:
        """Execute an iron condor spread"""
        tws = self.connection_manager.get_tws()
        if not tws:
            print("No TWS connection available")
            return False
            
        # Get current market price
        spx_price = tws.spx_price
        if not spx_price:
            print("Unable to get current SPX price")
            return False
            
        print(f"Current SPX price: {spx_price}")
        
        # Calculate initial strikes based on current price
        initial_put_strike = round((spx_price - 50) / 5) * 5  # Start 50 points below current price
        initial_call_strike = round((spx_price + 50) / 5) * 5  # Start 50 points above current price
        
        # Get expiry date (0 DTE)
        expiry = get_expiry_from_dte(0)
        
        print(f"\nLooking for 0 DTE options expiring: {expiry}")
        
        # Find all required options
        short_put = find_target_delta_option(tws, expiry, "P", initial_put_strike, 0.16)
        if not short_put:
            print("Failed to find short put")
            return False
            
        long_put = find_target_delta_option(tws, expiry, "P", short_put.contract.strike - 5, 0.08)
        if not long_put:
            print("Failed to find long put")
            return False
            
        short_call = find_target_delta_option(tws, expiry, "C", initial_call_strike, 0.16)
        if not short_call:
            print("Failed to find short call")
            return False
            
        long_call = find_target_delta_option(tws, expiry, "C", short_call.contract.strike + 5, 0.08)
        if not long_call:
            print("Failed to find long call")
            return False
        
        # Submit the order
        order_id = tws.submit_iron_condor(
            put_wing_contract=long_put.contract,
            put_contract=short_put.contract,
            call_contract=short_call.contract,
            call_wing_contract=long_call.contract,
            quantity=1,
            total_credit=1.00  # Minimum credit we want to receive
        )
        
        if not order_id:
            print("Failed to submit order")
            return False
            
        # Monitor the order
        filled = tws.monitor_order(order_id, timeout_seconds=300)
        
        if filled:
            # Record the trade in database
            db = TradeDatabase()
            db.record_trade(
                trade_name="IC_0DTE",
                trade_type="IRON_CONDOR",
                entry_time=datetime.now(pytz.timezone('US/Eastern')),
                expiry=expiry,
                put_strike=short_put.contract.strike,
                put_wing_strike=long_put.contract.strike,
                call_strike=short_call.contract.strike,
                call_wing_strike=long_call.contract.strike,
                quantity=1,
                spx_price=spx_price
            )
            return True
            
        return False

def execute_dc_config_2(connection_manager):
    """Execute the second double calendar configuration"""
    executor = TradeExecutor(connection_manager)
    return executor.execute_double_calendar(DC_CONFIG_2)

def execute_dc_config_3(connection_manager):
    """Execute the third double calendar configuration"""
    executor = TradeExecutor(connection_manager)
    return executor.execute_double_calendar(DC_CONFIG_3)

def execute_dc_config_4(connection_manager):
    """Execute the fourth double calendar configuration"""
    executor = TradeExecutor(connection_manager)
    return executor.execute_double_calendar(DC_CONFIG_4)

def execute_dc_config_5(connection_manager):
    """Execute the fifth double calendar configuration"""
    executor = TradeExecutor(connection_manager)
    return executor.execute_double_calendar(DC_CONFIG_5)

def execute_dc_config_6(connection_manager):
    """Execute the sixth double calendar configuration"""
    executor = TradeExecutor(connection_manager)
    return executor.execute_double_calendar(DC_CONFIG_6) 