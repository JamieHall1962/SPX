"""Handles actual trade execution"""
from typing import Optional
from datetime import datetime
import pytz
from config.trade_config import TradeConfig, TradeType
from connection.tws_manager import ConnectionManager
from trading.option_finder import find_target_delta_option, get_expiry_from_dte
from trading.database import TradeDatabase

class TradeExecutor:
    def __init__(self, connection_manager: ConnectionManager):
        self.connection_manager = connection_manager
    
    def execute_trade(self, config: TradeConfig) -> bool:
        """Execute a trade based on its configuration"""
        if config.trade_type == TradeType.DOUBLE_CALENDAR:
            return self.execute_double_calendar(config)
        elif config.trade_type == TradeType.IRON_CONDOR:
            return self.execute_iron_condor(config)
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
        
        # Get expiry dates from leg configs
        near_expiry = get_expiry_from_dte(config.legs[1].dte)  # Short put DTE
        far_expiry = get_expiry_from_dte(config.legs[0].dte)   # Long put DTE
        
        print(f"\nLooking for options with:")
        print(f"Near-term expiry: {near_expiry}")
        print(f"Far-term expiry: {far_expiry}")
        
        # Find all required options using leg configs
        near_put = find_target_delta_option(tws, near_expiry, "P", spx_price, config.legs[1].delta_target)
        far_put = find_target_delta_option(tws, far_expiry, "P", near_put.contract.strike + config.legs[0].strike_offset, None)
        near_call = find_target_delta_option(tws, near_expiry, "C", spx_price, config.legs[3].delta_target)
        far_call = find_target_delta_option(tws, far_expiry, "C", near_call.contract.strike + config.legs[2].strike_offset, None)
        
        # Submit the order
        order_id = tws.submit_double_calendar(
            short_put_contract=near_put.contract,
            long_put_contract=far_put.contract,
            short_call_contract=near_call.contract,
            long_call_contract=far_call.contract,
            quantity=1,  # Default to 1 contract
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
                quantity=1,
                spx_price=spx_price
            )
            return True
            
        return False
    
    def execute_iron_condor(self, config: TradeConfig) -> bool:
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
        
        # Get expiry from config
        expiry = get_expiry_from_dte(config.legs[0].dte)
        
        # Find options using leg configs
        short_put = find_target_delta_option(tws, expiry, "P", spx_price, config.legs[1].delta_target)
        long_put = find_target_delta_option(tws, expiry, "P", short_put.contract.strike + config.legs[0].strike_offset, None)
        short_call = find_target_delta_option(tws, expiry, "C", spx_price, config.legs[2].delta_target)
        long_call = find_target_delta_option(tws, expiry, "C", short_call.contract.strike + config.legs[3].strike_offset, None)
        
        # Submit the order
        order_id = tws.submit_iron_condor(
            put_wing_contract=long_put.contract,
            put_contract=short_put.contract,
            call_contract=short_call.contract,
            call_wing_contract=long_call.contract,
            quantity=1,  # Default to 1 contract
            total_credit=config.min_credit
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